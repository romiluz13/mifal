"""The five harnesses: where each one reads its rules today, and how the Guide reaches it."""
from __future__ import annotations

import errno
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path

from . import codex_config as cc

NAMES = ("claude", "codex", "droid", "pi", "opencode")
TITLES = {"claude": "Claude Code", "codex": "Codex", "droid": "Droid", "pi": "Pi", "opencode": "OpenCode"}
IMPORT = "@~/.agents/mifal/AGENTS.md"
CODEX_CAP = 32 * 1024
PI_ORDER = ("AGENTS.override.md", "AGENTS.md", "AGENTS.MD", "CLAUDE.md", "CLAUDE.MD")
OPENCODE_FALLBACK_OFF = ("OPENCODE_DISABLE_CLAUDE_CODE", "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT")
BLOCK = re.compile(r"<!-- mifal:begin [^\n]*-->\n.*?<!-- mifal:end -->\n", re.S)
FENCE = re.compile(r"^ {0,3}(```|~~~)")


class Refused(Exception):
    """A harness root the installer will not guess at."""


@dataclass
class Wiring:
    name: str
    root: Path
    rules: Path
    skip: str | None = None
    warn: str | None = None

    @property
    def mode(self) -> str:
        return "import" if self.name == "claude" else "text"


def _root(env, variable, default: Path, empty_is_unset=False) -> Path:
    if variable not in env or (empty_is_unset and env[variable] == ""):
        return default
    value = env[variable]
    if not os.path.isabs(value):
        raise Refused(f"mifal: {variable} is set to {value!r}, which is empty or relative. "
                         f"Unset it or set it to an absolute path, then run the installer again.")
    return Path(value)


def config_home(home: Path, env) -> Path:
    return _root(env, "XDG_CONFIG_HOME", home / ".config", empty_is_unset=True)


def roots(home: Path, env) -> dict:
    """Each harness's root folder, as the harness itself finds it, before realpath resolution."""
    xdg = config_home(home, env)
    return {
        "claude": _root(env, "CLAUDE_CONFIG_DIR", home / ".claude"),
        "codex": _root(env, "CODEX_HOME", home / ".codex"),
        "droid": home / ".factory",
        "pi": _root(env, "PI_CODING_AGENT_DIR", home / ".pi" / "agent"),
        "opencode": _root(env, "OPENCODE_CONFIG_DIR", xdg / "opencode"),
    }


VARIABLES = {"claude": "CLAUDE_CONFIG_DIR", "codex": "CODEX_HOME", "pi": "PI_CODING_AGENT_DIR",
             "opencode": "OPENCODE_CONFIG_DIR"}


def recorded_env(data: dict, env, show=str):
    """(env, notes): the environment an update or a doctor run uses beside the recorded Homes, which it reaches by
    their recorded roots. The agents' root variables are removed, so the shell's cannot add or move a Home. A
    manifest without a harness record passes env unchanged. A variable the shell set to a Home Mifal does not serve
    is noted."""
    records = data.get("harnesses") or {}
    if not records:
        return env, []
    notes = []
    for name, variable in VARIABLES.items():
        served = [r["root"] for r in records.get(name, []) if r["status"] == "wired"]
        shell = env.get(variable)
        if served and shell and os.path.realpath(shell) not in {os.path.realpath(r) for r in served}:
            shown = [show(r) for r in served]
            listed = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]
            notes.append(f"note {variable} is {show(shell)}, but Mifal serves {listed}; "
                         f"to serve another home, run ./install.sh --home {shlex.quote(f'{name}={shell}')}")
    return {k: v for k, v in env.items() if k not in VARIABLES.values()}, notes


def unserved(home: Path, data: dict, env, show=str, unrecorded_only=False) -> list:
    """A note for each harness detected in the shell's environment that the install does not serve. With
    unrecorded_only (the doctor), a harness the Manifest records as skipped is left out, because the doctor
    explains it already, and a Manifest that records none lists every detected harness; an update gives no
    notes then, because it wires them."""
    records = data.get("harnesses") or {}
    if not records and not unrecorded_only:
        return []
    found = roots(home, env)
    return [f"note found {name} at {show(found[name])}, not served; run ./install.sh to add it"
            for name in detect(home, env, found)
            if not any(r["status"] == "wired" for r in records.get(name, [])) and not (unrecorded_only and name in records)]


def _binary(name, env) -> bool:
    found = shutil.which(name, path=env.get("PATH", ""))
    if not found:
        return False
    real = os.path.realpath(found)
    return os.path.isfile(real) and os.access(real, os.X_OK)


def detect(home: Path, env, found_roots: dict) -> list:
    """Harnesses whose real binary is on PATH or whose home folder exists."""
    homes = dict(found_roots, pi=found_roots["pi"] if "PI_CODING_AGENT_DIR" in env else home / ".pi")
    return [n for n in NAMES if _binary(n, env) or homes[n].is_dir()]


def _names(folder: Path) -> set:
    return set(os.listdir(folder)) if folder.is_dir() else set()


def reads_now(name, home: Path, env, root: Path | None = None):
    """The rules file the harness reads today, or None when it reads none."""
    root = root or roots(Path(home), env)[name]
    names = _names(root)
    if name == "pi":
        order = PI_ORDER
    elif name == "codex":
        order = ("AGENTS.override.md", "AGENTS.md")
    else:
        order = ("CLAUDE.md",) if name == "claude" else ("AGENTS.md",)
    first = next((n for n in order if n in names), None)
    if first:
        return root / first
    if name == "opencode" and not any((env.get(v) or "").lower() in ("true", "1") for v in OPENCODE_FALLBACK_OFF):
        fallback = Path(env.get("OPENCODE_TEST_HOME") or env.get("HOME") or home) / ".claude" / "CLAUDE.md"
        return fallback if fallback.is_file() else None
    return None


@dataclass
class SkillFilters:
    coverage: str
    warnings: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unreadable: bool = False


@dataclass(frozen=True)
class SettingsFacts:
    file: str
    version: str
    format: str
    schema: str
    parser: object
    pool: bool = False


@dataclass
class SettingsRead:
    text: str | None = None
    failure: tuple[str, str] | None = None
    unreadable: bool = False
    missing: bool = False
    invalid_utf8: bool = False


CREDENTIAL_NAMES = frozenset(("auth", "auth.json", "oauth.json", "token", "tokens.json", "credentials",
                             "credentials.json", ".credentials.json", ".claude.json"))


def read_settings(config: Path, facts: SettingsFacts, show=str) -> SettingsRead:
    where, shape = show(config), facts.format
    linked = False
    regular = (f"{where} is not a regular {shape} file; exclusions unknown",
               f"make {where} a regular {shape} file, then run mifal doctor again")
    try:
        linked = config.is_symlink()
        target = config.resolve(strict=True)
        # Python 3.9 resolve can leave the original link unresolved during an atomic swap.
        if linked and target == config.absolute() or target.is_symlink():
            return SettingsRead(failure=(f"{where} has a looping or changing link; exclusions unknown",
                f"replace the looping or changing link at {where} with an existing regular {shape} file, then run mifal doctor again"), unreadable=True)
        credential = target.name.lower() in CREDENTIAL_NAMES
        suffixes = ('.json', '.jsonc') if shape == 'JSONC' else ('.' + shape.lower(),)
        wrong_shape = target.suffix.lower() not in suffixes and not (shape == 'gitignore' and target.name.lower() == '.gitignore')
        if credential or wrong_shape:
            if not stat.S_ISREG(target.stat().st_mode):
                return SettingsRead(failure=regular, unreadable=True)
            if credential:
                return SettingsRead(failure=(f"{where} resolves to a credential, token or auth path; exclusions unknown",
                    f"point {where} at a regular {shape} file for {facts.version} settings; doctor never reads credential files"))
            return SettingsRead(failure=(f"{where} does not point to a regular {shape} file; exclusions unknown",
                f"make {where} point to a regular {shape} file, then run mifal doctor again"), unreadable=True)
        fd = os.open(target, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return SettingsRead(failure=regular, unreadable=True)
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                text = stream.read().decode('utf-8')
        finally:
            os.close(fd)
        return SettingsRead(text=text)
    except FileNotFoundError:
        if not linked:
            return SettingsRead(missing=True)
        return SettingsRead(failure=(f"{where} points to a missing file; {facts.version} reads no settings from it",
            f"point {where} at an existing regular {shape} file, then run mifal doctor again"), unreadable=True)
    except RuntimeError:
        return SettingsRead(failure=(f"{where} has a link loop; exclusions unknown",
            f"replace the looping link at {where} with an existing regular {shape} file, then run mifal doctor again"), unreadable=True)
    except UnicodeError:
        return SettingsRead(failure=(f"{where} is not valid UTF-8 {shape}; exclusions unknown",
            f"repair the {shape} in {where}, then run mifal doctor again"), invalid_utf8=True)
    except OSError as error:
        if error.errno == errno.ELOOP:
            return SettingsRead(failure=(f"{where} has a link loop or changed to a link during the read; exclusions unknown",
                f"replace the looping or changing link at {where} with an existing regular {shape} file, then run mifal doctor again"), unreadable=True)
        return SettingsRead(failure=(f"{where} cannot be read; exclusions unknown",
            f"restore read access to {where}, then run mifal doctor again"), unreadable=True)


def _codex_filters(text, result, facts, home, root, pool, skills, show):
    where = show(root / facts.file)
    try:
        table = cc.parse(text).get("skills", {})
    except cc.Invalid:
        result.warnings.append((f"{where} is not valid UTF-8 TOML; exclusions unknown",
                                f"repair the TOML in {where}, then run mifal doctor again"))
        return result
    entries = table.get("config", []) if isinstance(table, dict) else None
    if not isinstance(entries, list) or any(
            not isinstance(entry, dict) or type(entry.get("enabled")) is not bool
            or "path" in entry and not isinstance(entry["path"], str)
            or "name" in entry and not isinstance(entry["name"], str)
            for entry in entries):
        result.warnings.append((f"{where} has invalid skills.config; exclusions unknown",
                                f"use [[skills.config]] entries with one path or name selector and boolean enabled in {where}"))
        return result
    documents = {os.path.realpath(pool / skill / "SKILL.md"): skill for skill in skills}
    disabled = set()
    for index, entry in enumerate(entries, 1):
        if ("path" in entry) == ("name" in entry) or "name" in entry and not entry["name"].strip():
            result.notes.append(f"skipped [[skills.config]] entry {index} in {where}: "
                                "needs one path or nonblank name selector; other entries are still checked")
            continue
        if "path" in entry:
            path = entry["path"]
            if "\0" in path:
                continue
            if path == "~" or path.startswith("~/"):
                path = home / path[2:].lstrip("/")
            selector = root / path
            skill = None
            for document, candidate in documents.items():
                try:
                    matches = os.path.samefile(selector, document)
                except OSError:
                    matches = os.path.realpath(os.path.normpath(selector)) == document
                if matches:
                    skill = candidate
                    break
        else:
            skill = entry["name"].strip()
        if skill in skills:
            if entry["enabled"]:
                disabled.discard(skill)
            else:
                disabled.add(skill)
    if not disabled:
        result.coverage = f"no exclusion found in {where}; reads skill keys only ({facts.schema})"
    for skill in sorted(disabled):
        result.warnings.append((f"{skill}: configured exclusion detected in {where} at [[skills.config]]",
                                f"set enabled = true or remove the matching entry in {where}; restart Codex"))
    return result


CODEX_SETTINGS = SettingsFacts("config.toml", "Codex 0.166.0", "TOML",
    "supports Codex 0.166.0 [[skills.config]] (path or name, enabled); Codex version and session -c overrides: unknown",
    _codex_filters)


def _invalid(result, where, key, shape='JSON'):
    result.warnings.append((f"{where} has invalid {key}; exclusions unknown",
                            f"repair {key} in {where} using the supported {shape} schema, then run mifal doctor again"))


def _json(text, result, where, shape='JSON'):
    def invalid_constant(value):
        raise ValueError('invalid JSON number')

    try:
        data = json.loads(text.lstrip('\ufeff'), parse_constant=invalid_constant)
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, RecursionError):
        _invalid(result, where, shape + ' settings', shape)
        return None


def _hidden(result, skill, where, key, fix):
    result.warnings.append((f"{skill}: configured exclusion detected in {where} at {key}", fix))


def _claude_filters(reads, result, home, root, pool, skills, show):
    for facts, path, text in reads:
        where = show(path)
        data = _json(text if text.lstrip("\ufeff").strip() else "{}", result, where)
        if data is None:
            continue
        overrides = data.get('skillOverrides', {})
        if not isinstance(overrides, dict) or any(value not in ('on', 'name-only', 'user-invocable-only', 'off')
                                                  for value in overrides.values()):
            _invalid(result, where, 'skillOverrides')
            continue
        for skill in sorted(skills):
            if overrides.get(skill) in ('off', 'user-invocable-only'):
                _hidden(result, skill, where, 'skillOverrides',
                        f"set skillOverrides.{skill} to on or remove its entry in {where}; restart Claude Code")
    return result


CLAUDE_SETTINGS = SettingsFacts('settings.json', 'Claude Code 2.1.316', 'JSON',
    'supports Claude Code 2.1.316 skillOverrides (on, name-only, user-invocable-only, off); '
    'project, local, managed, flags and synced settings are not read; effective session scope: unknown', _claude_filters)


def _droid_filters(reads, result, home, root, pool, skills, show):
    for facts, path, text in reads:
        where = show(path)
        try:
            cleaned = _jsonc(text, trailing_commas=False)
        except ValueError:
            _invalid(result, where, 'JSONC settings', 'JSONC')
            continue
        data = _json(cleaned, result, where, 'JSONC')
        if data is None:
            continue
        disabled = data.get('disabledSkills', [])
        if not isinstance(disabled, list) or any(not isinstance(value, str) for value in disabled):
            _invalid(result, where, 'disabledSkills')
            continue
        names = {re.sub('-+', '-', re.sub('[^a-z0-9-]', '-', value.lower())).strip('-') for value in disabled}
        for skill in sorted(skills & names):
            _hidden(result, skill, where, 'disabledSkills',
                    f"remove {skill} from disabledSkills in {where}; restart Droid")
    return result


DROID_SETTINGS = SettingsFacts('settings.json', 'Droid 1.1.0', 'JSONC',
    'supports Droid 1.1.0 disabledSkills (normalized names; JSON comments allowed, trailing commas refused); '
    'project settings and frontmatter are not read; '
    'effective session scope: unknown', _droid_filters)


def _glob(value, pattern, dot=False):
    if any(token in pattern for token in ('{', '}', '@(', '?(', '*(', '+(', '!(', '[[:', '[^')):
        raise ValueError('unsupported pattern syntax')
    if not dot and pattern.startswith('#'):
        return False
    negate = False
    if not dot:
        while pattern.startswith('!'):
            negate = not negate
            pattern = pattern[1:]
    parts, targets = pattern.split('/'), value.split('/')

    def matches(p, v):
        if not p:
            return not v
        if p[0] == '**':
            return matches(p[1:], v) or bool(v) and (dot or not v[0].startswith('.')) and matches(p, v[1:])
        return bool(v) and (dot or not v[0].startswith('.') or p[0].startswith('.')) and \
            fnmatch.fnmatchcase(v[0], p[0]) and matches(p[1:], v[1:])

    matched = matches(parts, targets)
    return not matched if negate else matched


def _pi_pattern(pattern, home):
    if pattern.startswith('file://'):
        from urllib.parse import unquote, urlsplit
        url = urlsplit(pattern)
        if url.netloc not in ('', 'localhost'):
            raise ValueError('unsupported file URL')
        if re.search('%2f', url.path, re.I):
            raise ValueError('encoded file URL separator')
        pattern = unquote(url.path, errors='strict')
        if any(part in ('.', '..') for part in pattern.split('/')):
            raise ValueError('unsupported file URL dot segments')
    if pattern == '~' or pattern.startswith('~/'):
        trailing = pattern.endswith('/')
        pattern = os.path.normpath(str(home) + pattern[1:])
        if trailing and pattern != '/':
            pattern += '/'
    return pattern.replace('\\', '/')


def _pi_matches(document, pattern, base, home, exact=False):
    if exact and pattern.startswith(('./', '.\\')):
        pattern = pattern[2:]
    pattern = _pi_pattern(pattern, home)
    paths = [os.path.relpath(document, base), str(document), os.path.relpath(document.parent, base), str(document.parent)]
    if exact:
        return pattern in [value.replace('\\', '/') for value in paths]
    return any(_glob(value.replace('\\', '/'), pattern) for value in paths + [document.name, document.parent.name])


def _ignored(document, folder, text):
    relative = document.relative_to(folder).as_posix()
    pieces = relative.split('/')
    for count in range(1, len(pieces) + 1):
        candidate = '/'.join(pieces[:count])
        directory = count < len(pieces)
        ignored = False
        for line in text.splitlines():
            pattern = line.rstrip(' ')
            if not pattern or pattern.startswith('#'):
                continue
            if '\\' in pattern:
                raise ValueError('unsupported ignore escape')
            negate = pattern.startswith('!')
            if negate:
                pattern = pattern[1:]
            directory_only = pattern.endswith('/')
            if directory_only:
                pattern = pattern[:-1]
            anchored = pattern.startswith('/')
            pattern = pattern.lstrip('/')
            target = candidate if anchored or '/' in pattern else pieces[count - 1]
            if (not directory_only or directory) and _glob(target.lower(), pattern.lower(), dot=True):
                ignored = not negate
        if ignored:
            return True
    return False


def _pi_filters(reads, result, home, root, pool, skills, show):
    patterns = []
    ignores = {}
    for facts, path, text in reads:
        if facts.format == 'gitignore':
            ignores[path.parent] = (path, text)
            continue
        data = _json(text, result, show(path))
        if data is None:
            continue
        patterns = data.get('skills', [])
        if isinstance(patterns, dict):
            patterns = patterns.get('customDirectories', [])
        if not isinstance(patterns, list) or any(not isinstance(pattern, str) for pattern in patterns):
            _invalid(result, show(path), 'skills')
            patterns = []
    unknown = set()
    for skill in sorted(skills):
        candidates = [(pool / skill / 'SKILL.md', pool.parent)]
        alias = root / 'skills' / skill / 'SKILL.md'
        try:
            if os.path.samefile(alias, candidates[0][0]):
                candidates.insert(0, (alias, root))
        except OSError:
            pass
        hidden = None
        for document, base in candidates:
            ignore = ignores.get(document.parent.parent)
            try:
                if ignore and _ignored(document, ignore[0].parent, ignore[1]):
                    hidden = (show(ignore[0]), '.gitignore')
                    continue
            except (ValueError, RecursionError):
                unknown.add((show(ignore[0]), '.gitignore pattern syntax'))
            try:
                excluded = any(_pi_matches(document, pattern[1:], base, home) for pattern in patterns if pattern.startswith('!'))
                if any(_pi_matches(document, pattern[1:], base, home, exact=True) for pattern in patterns if pattern.startswith('+')):
                    excluded = False
                if any(_pi_matches(document, pattern[1:], base, home, exact=True) for pattern in patterns if pattern.startswith('-')):
                    excluded = True
                if excluded:
                    hidden = (show(root / 'settings.json'), 'skills')
            except (ValueError, RecursionError):
                unknown.add((show(root / 'settings.json'), 'skills pattern syntax'))
        if hidden:
            where, key = hidden
            _hidden(result, skill, where, key,
                    f"remove the matching exclusion for {skill} from {key} in {where}; restart Pi")
    for where, key in sorted(unknown):
        result.warnings.append((f"{where} uses pattern syntax outside the supported Pi audit; exclusions unknown",
                                f"inspect {key} in {where} with Pi 1.4.0; this audit supports ordinary globs and exact paths"))
    return result


PI_SETTINGS = SettingsFacts('settings.json', 'Pi 1.4.0', 'JSON',
    'supports Pi 1.4.0 skills (!glob, +exact, -exact) and root skills-folder .gitignore; '
    'complex pattern and dot-segment file-URL syntax: unknown; project, packages, added resource paths, nested ignore files, '
    '.ignore and .fdignore are not read; effective session scope: unknown', _pi_filters)
PI_IGNORE = SettingsFacts('skills/.gitignore', 'Pi 1.4.0', 'gitignore', PI_SETTINGS.schema, _pi_filters)
PI_POOL_IGNORE = SettingsFacts('.gitignore', 'Pi 1.4.0', 'gitignore', PI_SETTINGS.schema, _pi_filters, pool=True)


def _jsonc(text, trailing_commas=True):
    output = []
    quoted = escaped = False
    i = 0
    while i < len(text):
        char = text[i]
        if not quoted and text[i:i + 2] in ('//', '/*'):
            if text[i:i + 2] == '//':
                end = text.find('\n', i + 2)
                i = len(text) if end < 0 else end
            else:
                end = text.find('*/', i + 2)
                if end < 0:
                    raise ValueError('unclosed comment')
                i = end + 2
            output.append(' ')
            continue
        if char == '"' and not escaped:
            quoted = not quoted
        escaped = char == '\\' and quoted and not escaped
        output.append(char)
        i += 1
    text = ''.join(output)
    if not trailing_commas:
        return text
    output = []
    quoted = escaped = False
    for i, char in enumerate(text):
        if char == '"' and not escaped:
            quoted = not quoted
        escaped = char == '\\' and quoted and not escaped
        if char == ',' and not quoted and text[i + 1:].lstrip().startswith(('}', ']')):
            continue
        output.append(char)
    return ''.join(output)


def _oc_match(value, pattern):
    pattern = re.escape(pattern.replace('\\', '/')).replace(r'\*', '.*').replace(r'\?', '.')
    if pattern.endswith(r'\ .*'):
        pattern = pattern[:-4] + '( .*)?'
    flags = re.S | (re.I if os.name == 'nt' else 0)
    return re.fullmatch(pattern, value.replace('\\', '/'), flags) is not None


def _opencode_filters(reads, result, home, root, pool, skills, show):
    merged = {}
    for facts, path, text in reads:
        where = show(path)
        try:
            cleaned = _jsonc(text)
        except ValueError:
            _invalid(result, where, 'JSONC settings', 'JSONC')
            continue
        data = _json(cleaned, result, where, 'JSONC')
        if data is None:
            continue
        permission = data.get('permission', {})
        if isinstance(permission, str):
            permission = {'*': permission}
        if not isinstance(permission, dict) or any(
                not isinstance(value, (str, dict)) or isinstance(value, str) and value not in ('allow', 'ask', 'deny')
                or isinstance(value, dict) and any(action not in ('allow', 'ask', 'deny') for action in value.values())
                for value in permission.values()):
            _invalid(result, where, 'permission.skill', 'JSONC')
            continue
        if any(token in json.dumps(permission) for token in ('{env:', '{file:')):
            _invalid(result, where, 'permission substitutions (not expanded)', 'JSONC')
            continue
        for key, value in permission.items():
            if isinstance(value, str):
                merged[key] = (value, where)
            else:
                previous = merged.get(key)
                rules = previous if isinstance(previous, dict) else {}
                rules.update({pattern: (action, where) for pattern, action in value.items()})
                merged[key] = rules
    for skill in sorted(skills):
        winner = None
        for key, value in merged.items():
            if not _oc_match('skill', key):
                continue
            for pattern, action in (value.items() if isinstance(value, dict) else [('*', value)]):
                if pattern == '~' or pattern.startswith('~/'):
                    pattern = str(home) + pattern[1:]
                elif pattern.startswith('$HOME'):
                    pattern = str(home) + pattern[5:]
                if _oc_match(skill, pattern):
                    winner = (action[0], action[1], key)
        if winner and winner[0] == 'deny':
            where, key = winner[1:]
            key = 'permission.' + key
            _hidden(result, skill, where, key,
                    f"set the matching {key} rule for {skill} to allow or remove it in {where}; restart OpenCode")
    return result


OPENCODE_SETTINGS = SettingsFacts('config.json', 'OpenCode 1.19.4', 'JSONC',
    'supports OpenCode 1.19.4 permission.skill (allow, ask, deny or ordered pattern map), '
    'global config.json then opencode.json then opencode.jsonc (overridden directories: opencode.json/jsonc only); '
    'legacy TOML migration, project, managed, agent, other global Homes and env/CLI settings are not read; '
    'effective session scope: unknown', _opencode_filters)
OPENCODE_JSON = SettingsFacts('opencode.json', 'OpenCode 1.19.4', 'JSONC', OPENCODE_SETTINGS.schema, _opencode_filters)
OPENCODE_JSONC = SettingsFacts('opencode.jsonc', 'OpenCode 1.19.4', 'JSONC', OPENCODE_SETTINGS.schema, _opencode_filters)
SETTINGS = {"codex": (CODEX_SETTINGS,), 'claude': (CLAUDE_SETTINGS,), 'droid': (DROID_SETTINGS,),
            'pi': (PI_SETTINGS, PI_IGNORE, PI_POOL_IGNORE),
            'opencode': (OPENCODE_SETTINGS, OPENCODE_JSON, OPENCODE_JSONC)}


def skill_filters(name, home: Path, root: Path, pool: Path, skills, show=str, env=None) -> SkillFilters | None:
    files = SETTINGS.get(name)
    if files is None:
        return None
    if name == 'opencode':
        try:
            global_root = config_home(home, env or {}) / 'opencode'
        except Refused:
            global_root = None
        try:
            is_global = global_root is not None and os.path.samefile(root, global_root)
        except OSError:
            is_global = global_root is not None and root.absolute() == global_root.absolute()
        if not is_global:
            files = files[1:]
    paths = [(facts, (pool if facts.pool else root) / facts.file) for facts in files]
    listed = ', '.join(show(path) for _, path in paths)
    result = SkillFilters(f"reads {listed} skill keys only ({files[0].schema})")
    reads = []
    for facts, config in paths:
        read = read_settings(config, facts, show)
        if read.failure:
            result.warnings.append(read.failure)
            result.unreadable |= read.unreadable
        elif not read.missing:
            reads.append((facts, config, read.text))
    if name == 'codex':
        if reads:
            return CODEX_SETTINGS.parser(reads[0][2], result, CODEX_SETTINGS, home, root, pool, skills, show)
    else:
        files[0].parser(reads, result, home, root, pool, skills, show)
    if not result.warnings:
        result.coverage = f"no exclusion found in {listed}; reads skill keys only ({files[0].schema})"
    return result


def _open_fence(text: str) -> bool:
    fenced = False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
    return fenced


def _holds_more_than_block(path: Path) -> bool:
    try:
        return bool(BLOCK.sub("", path.read_text(encoding="utf-8", errors="replace")).strip())
    except OSError:
        return True


def plan(name, home: Path, env, root: Path, show) -> Wiring:
    """Where the Guide goes for this harness, or why Mifal leaves it alone."""
    rules = root / ("CLAUDE.md" if name == "claude" else "AGENTS.md")
    w = Wiring(name, root, rules)
    now = reads_now(name, home, env, root)
    if now == rules:
        now = None
    if now is not None and now.name.startswith("AGENTS.override"):
        w.skip = (f"skip {name}: it reads {show(now)}, which overrides {show(rules)}. Mifal does not hide your "
                  f"override. To wire {TITLES[name]}, move what you want to keep into {show(rules)}, remove the "
                  f"override and run the installer again.")
    elif now is not None and name != "opencode":
        w.skip = (f"skip {name}: it reads {show(now)} now. Mifal's block belongs in {show(rules)}, and once that "
                  f"file exists {TITLES[name]} stops reading {show(now)}. To wire it, copy what you want to keep "
                  f"from {show(now)} into {show(rules)} and run the installer again.")
    elif now is not None and _holds_more_than_block(now):
        w.warn = (f"{show(now)}: OpenCode reads it now, and stops once Mifal writes {show(rules)}; copy what you "
                  f"want to keep from it into {show(rules)}")
    elif rules.is_file() and _open_fence(rules.read_text(encoding="utf-8")):
        w.skip = f"skip {name}: {show(rules)} ends inside an open code fence; close it and run the installer again."
    return w


def guide_digest(guide_text: str) -> str:
    return hashlib.sha256(guide_text.encode("utf-8")).hexdigest()


def block(name, version: str, guide_text: str) -> str:
    body = IMPORT if name == "claude" else guide_text.rstrip("\n")
    return (f"<!-- mifal:begin version={version} guide=sha256:{guide_digest(guide_text)} -->\n"
            f"{body}\n<!-- mifal:end -->\n")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
