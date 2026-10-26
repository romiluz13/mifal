"""Option C (ADR 0005): the Guide as one Mifal-marked developer_instructions key at the top of a named Codex Home's
config.toml, for a Home whose AGENTS.md links to a shared file. Mifal owns only the marked block's bytes; every other
byte of the file keeps its place. Messages name paths and the key, never a config value."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .manifest import MISSING, state

KEY = "developer_instructions"
BEGIN = "# mifal:begin "
END = "# mifal:end"
MARKER = re.compile(r"^[ \t]*#[ \t]*mifal:(begin|end)\b", re.M)
VENDOR = Path(__file__).resolve().parents[2] / "third_party" / "tomli"
SPELLED = ("~/.agents/mifal/AGENTS.md", "$HOME/.agents/mifal/AGENTS.md", "${HOME}/.agents/mifal/AGENTS.md")
HANDLERS = ("command", "mcp_tool", "prompt", "agent")
REFERENCES = "your SessionStart command references the Guide; no key was added"


class Invalid(Exception):
    """A config.toml that is not UTF-8 TOML."""


def _tomli():
    name = "mifal_vendored_tomli"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, VENDOR / "__init__.py",
                                                      submodule_search_locations=[str(VENDOR)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read(path: Path) -> str:
    """The file's text exactly as stored, line endings included."""
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise Invalid("is not UTF-8")


def parse(text: str) -> dict:
    try:
        return _tomli().loads(text)
    except _tomli().TOMLDecodeError:
        raise Invalid("does not parse as TOML")


def sets_key(value) -> bool:
    """Whether the key appears at any depth: top level, dotted, or inside any table, profile or array of tables."""
    if isinstance(value, dict):
        return any(k == KEY or sets_key(v) for k, v in value.items())
    if isinstance(value, list):
        return any(sets_key(v) for v in value)
    return False


def newline(text: str) -> str:
    at = text.find("\n")
    return "\r\n" if at > 0 and text[at - 1] == "\r" else "\n"


def _escaped(line: str) -> str:
    out = []
    for i, ch in enumerate(line):
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\t":
            out.append("\\t")
        elif ch == " " and i == 0:
            # A line-ending backslash trims the next line's leading whitespace too.
            out.append("\\u0020")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return "".join(out)


def block(version: str, guide_text: str, nl: str = "\n") -> str:
    """The owned block. Each Guide newline is an escaped \\n followed by a line-ending backslash, so the file's own
    line endings never enter the value and parsing it yields exactly the Guide."""
    value = ("\\n\\" + nl).join(_escaped(line) for line in guide_text.split("\n"))
    return (f"{BEGIN}version={version} guide=sha256:{digest(guide_text)}{nl}"
            f'{KEY} = """\\{nl}{value}"""{nl}{END}{nl}')


def split(text: str, recorded: str):
    """(block, rest) when the file starts with exactly the recorded block and holds no other marker, else None."""
    marks = list(MARKER.finditer(text))
    if [m.group(1) for m in marks] != ["begin", "end"] or marks[0].start() != 0:
        return None
    end = text.find("\n", marks[1].start())
    cut = len(text) if end < 0 else end + 1
    if digest(text[:cut]) != recorded:
        return None
    return text[:cut], text[cut:]


def spellings(h) -> tuple:
    """The ways a hook command can name the installed Guide: through ~ or $HOME, the HOME path, or its realpath."""
    return SPELLED + (str(h.home / ".agents/mifal/AGENTS.md"), str(h.engine / "AGENTS.md"))


def _references(command: str, spellings) -> bool:
    return any(re.search(r"(?<![\w./~${}-])" + re.escape(s) + r"(?![\w./-])", command) for s in spellings)


def _session_start(events, spellings):
    """The kind of one event table in the shape both sources share: clear, reference, other or unknown. A handler that does not name the Guide is one Mifal cannot classify, since it does not read scripts."""
    groups = events.get("SessionStart", []) if isinstance(events, dict) else None
    if not isinstance(groups, list) or not all(isinstance(g, dict) and isinstance(g.get("hooks", []), list)
                                               for g in groups):
        return "unknown"
    handlers = [x for g in groups for x in g.get("hooks", [])]
    if not all(isinstance(x, dict) and x.get("type") in HANDLERS for x in handlers):
        return "unknown"
    commands = [[x.get(k) for k in ("command", "commandWindows", "command_windows")]
                for x in handlers if x["type"] == "command"]
    if not all(isinstance(c[0], str) and all(v is None or isinstance(v, str) for v in c[1:]) for c in commands):
        return "unknown"
    if any(v and _references(v, spellings) for c in commands for v in c):
        return "reference"
    return "other" if handlers else "clear"


def _file_hooks(path: Path, spellings, show):
    now = state(path)
    unknown = ("unknown", f"Mifal cannot classify {show(path)}, so it adds no key", now)
    if now == MISSING:
        return "clear", None, now
    if now[0] != "file":
        return unknown
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return unknown
    if not isinstance(data, dict) or set(data) - {"description", "hooks"}:
        return unknown
    kind = _session_start(data.get("hooks", {}), spellings)
    if kind == "unknown":
        return unknown
    if kind == "reference":
        return "pending", REFERENCES, now
    if kind == "other":
        return "pending", f"{show(path)}: it has a SessionStart hook Mifal cannot classify; no key was added", now
    return "clear", None, now


def _inline_hooks(config: Path, spellings, show):
    """The [hooks] table of config.toml, whose event tables Codex reads like hooks.json's. Its `state` map holds
    trust records, not hooks, and is ignored. A config that cannot be read as TOML is the plan's to refuse."""
    try:
        if state(config)[0] != "file":
            return "clear", None
        table = parse(read(config)).get("hooks", {})
    except (Invalid, OSError):
        return "clear", None
    unknown = ("unknown", f"Mifal cannot classify the [hooks] table in {show(config)}, so it adds no key")
    if not isinstance(table, dict) or not isinstance(table.get("state", {}), dict):
        return unknown
    kind = _session_start({k: v for k, v in table.items() if k != "state"}, spellings)
    if kind == "unknown":
        return unknown
    if kind == "reference":
        return "pending", f"{show(config)}: your [hooks] SessionStart command references the Guide; no key was added"
    if kind == "other":
        return "pending", (f"{show(config)}: it has a [hooks] SessionStart hook Mifal cannot classify; "
                           "no key was added")
    return "clear", None


def hooks(root: Path, spellings, show) -> tuple:
    """(status, reason, state, source) of the Home's hooks, read as data in the shape Codex 0.164 reads
    (codex-rs/config/src/hook_config.rs): hooks.json and the [hooks] table of config.toml, both treated as active
    because the retained source lacks the loader and the official page says Codex merges them. Status is clear,
    pending or unknown; unknown wins, and hooks.json is named first. state is hooks.json's, source the file that
    decided. Nothing is run, followed or edited, and no command is ever printed."""
    status, reason, now = _file_hooks(root / "hooks.json", spellings, show)
    source = root / "hooks.json"
    config = root / "config.toml"
    if status != "unknown":
        inline, why = _inline_hooks(config, spellings, show)
        if inline == "unknown" or status == "clear" and inline != "clear":
            status, reason, source = inline, why, config
    return status, reason, now, source if status != "clear" else None


@dataclass
class Key:
    """One Home's option C plan: the new text to write, or why nothing is written."""
    status: str = "wired"
    reason: str | None = None
    text: str | None = None
    before: str | None = None
    block: str | None = None
    created: bool = False
    conflict: str | None = None
    keep: bool = False
    bound: list = field(default_factory=list)


def plan(config: Path, version: str, guide_text: str, entry, show) -> Key:
    """What to do with config: insert the block, refresh or keep it, or refuse. entry is the recorded key entry."""
    k = Key()
    where = show(config)
    now = state(config)
    k.bound.append((str(config), now))
    if now[0] == "link":
        k.conflict = f"{where}: is a symbolic link, and Mifal does not write through a link"
        return k
    if now != MISSING and now[0] != "file":
        k.conflict = f"{where}: is not a regular file"
        return k
    try:
        text = read(config) if now != MISSING else None
        original = parse(text) if text is not None else {}
    except Invalid as e:
        k.conflict = f"{where}: {e}, so Mifal cannot add {KEY}"
        k.keep = entry is not None
        return k
    k.before = text
    if entry:
        found = split(text or "", entry["sha256"])
        if found is None:
            k.conflict = (f"{where}: its Mifal {KEY} block changed since install; put it back as it was, or run "
                          "mifal uninstall and install again")
            k.keep = True
            return k
        old, rest = found
        if sets_key(parse(rest)):
            k.conflict = f"{where}: sets {KEY} outside Mifal's block"
            k.keep = True
            return k
        new = block(version, guide_text, newline(text))
        k.created = entry["created"]
        if new == old:
            k.keep = True
            return k
        k.text, k.block = new + rest, new
        return k
    if text is not None and MARKER.search(text):
        k.conflict = f"{where}: holds a Mifal marker this install did not write"
        return k
    if sets_key(original):
        k.conflict = f"{where}: already sets {KEY}, so Mifal adds none"
        return k
    new = block(version, guide_text, newline(text) if text else "\n")
    result = new + (text or "")
    try:
        parsed = parse(result)
    except Invalid:
        parsed = None
    if parsed is None or parsed.pop(KEY, None) != guide_text or parsed != original:
        k.conflict = f"{where}: would not parse with Mifal's {KEY} added"
        return k
    k.text, k.block, k.created = result, new, text is None
    return k
