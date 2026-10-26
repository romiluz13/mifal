"""The five harnesses: where each one reads its rules today, and how the Guide reaches it."""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path

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
