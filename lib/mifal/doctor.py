"""mifal doctor: prove an install is healthy. Read-only: it writes nothing, uses no network, runs no harness,
and opens no settings, token or credential file itself (`herdr status` loads Herdr's own config); it reads
Mifal's own files and the rules files it wired, and, in a Codex Home served through config.toml, only that file and
the Home's hooks.json."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from . import codex_config as cc
from . import harness
from . import herdr
from . import manifest as mf
from .install import Unreadable, engine_missing, moved_folders
from .manifest import expected, state

REINSTALL = "run ./install.sh in your Mifal clone; a file you edited stops it until you pass --overwrite-edits, " \
            "which saves a copy first"
ROOT_VARIABLES = ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "PI_CODING_AGENT_DIR", "OPENCODE_CONFIG_DIR",
                  "XDG_CONFIG_HOME")


class Report:
    def __init__(self, out):
        self.out, self.counts = out, {"PASS": 0, "WARN": 0, "FAIL": 0}

    def line(self, status, check, detail, fix=None):
        self.counts[status] += 1
        self.out(f"{status} {check}: {detail}")
        if fix:
            self.out(f"     fix: {fix}")


def _validator(h):
    path = h.pool / "team-lead" / "scripts" / "validate_contracts.py"
    spec = importlib.util.spec_from_file_location("mifal_installed_validator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return path, module


def doctor(h: mf.Home, env, out) -> int:
    r = Report(out)
    loaded = mf.load(h)
    if loaded is None:
        r.line("FAIL", "manifest", f"no Manifest at {h.show(h.manifest)}", "run ./install.sh in your Mifal clone")
        return 1
    data = loaded[0]
    if data.get("state") != "complete":
        r.line("FAIL", "manifest", "an install was interrupted", "run ./install.sh in your Mifal clone to roll it back")
        return 1
    show = h.show
    shell = env
    env, notes = harness.recorded_env(data, shell, show)
    for line in notes:
        out(line)

    for line in moved_folders(h, data.get("folders", {})):
        r.line("FAIL", "folders", line, "put the folder back where it was")

    layout = [h.engine / "bin" / "mifal", h.engine / "AGENTS.md", h.pool]
    missing = [show(p) for p in layout if not p.exists()]
    linked = os.path.islink(h.link) and os.readlink(h.link) == str(h.engine / "bin" / "mifal")
    if missing or not linked:
        r.line("FAIL", "layout", "missing " + ", ".join(missing + ([] if linked else [show(h.link)])), REINSTALL)
    else:
        r.line("PASS", "layout", f"engine {show(h.engine)}, Pool {show(h.pool)}, command {show(h.link)}")

    changed = [show(e["path"]) for e in data["entries"]
               if e["kind"] in ("file", "symlink") and state(Path(e["path"])) != expected(e)]
    if changed:
        more = f" and {len(changed) - 5} more" if len(changed) > 5 else ""
        r.line("FAIL", "manifest", f"{len(changed)} installed path(s) changed or missing: "
               + ", ".join(changed[:5]) + more, REINSTALL)
    else:
        r.line("PASS", "manifest", f"{sum(e['kind'] in ('file', 'symlink') for e in data['entries'])} paths as installed")

    try:
        absent = engine_missing(h, data)
    except Unreadable as e:
        r.line("WARN", "engine", f"completeness could not be checked: {e}",
               "restore the clone recorded in the Manifest at its installed revision, or clone Mifal again and run ./install.sh")
    else:
        if absent:
            r.line("WARN", "engine", f"{len(absent)} file(s) the installed revision installs are missing from "
                   f"{show(h.engine)}, e.g. {show(absent[0])}", "run mifal update")

    clone = (data.get("source") or {}).get("path")
    saved = [Path(e["path"]) for e in data["entries"] if e["kind"] == "backup" and os.path.lexists(e["backup"])]
    from_clone = sum(bool(clone) and p.is_relative_to(clone) for p in saved)
    if len(saved) > from_clone:
        out(f"note {len(saved) - from_clone} skill folder(s) or link(s) of yours are saved in "
            f"{show(h.engine / 'backup')}: a release took their names. To keep one under another name, copy it from "
            "there; mifal uninstall puts each back where it was when that place is free")
    if from_clone:
        out(f"note {from_clone} item(s) of yours from your Mifal clone are saved in {show(h.engine / 'backup')}: git "
            "ignored them and a release added tracked files where they were. They stay there after mifal uninstall "
            "while the clone has the release's files in their place; to keep one, copy it from there, but copying "
            "it back into the clone makes the clone's tracked file differ")

    guide = h.engine / "AGENTS.md"
    guide_sha = hashlib.sha256(guide.read_bytes()).hexdigest() if guide.is_file() else None
    blocks = {e["path"]: e for e in data["entries"] if e["kind"] == "block"}
    skills = sorted(p.name for p in h.pool.iterdir() if (p / "SKILL.md").is_file()) if h.pool.is_dir() else []
    pool_prefix = str(h.pool) + os.sep
    mifal_skills = {e["path"][len(pool_prefix):].split(os.sep, 1)[0] for e in data["entries"]
                    if e["kind"] in ("file", "symlink") and e["path"].startswith(pool_prefix)}
    keys = {e["path"]: e for e in data["entries"] if e["kind"] == "key"}
    for name, rec in sorted(mf.homes(data), key=lambda home: home[0]):
        if rec.get("delivery") == "config":
            _key(r, rec, keys.get(rec["config"]), guide_sha, h)
            continue
        if rec["status"] != "wired":
            w = harness.plan(name, h.home, env, Path(rec["root"]), show)
            if w.skip:
                why, _, fix = w.skip.partition(". ")
                r.line("FAIL", f"guide {name}", "not wired: " + why.split(": ", 1)[-1], fix)
            else:
                # The fix runs in a shell where the variable may be unset, so the command names the recorded root itself.
                variable = harness.VARIABLES.get(name)
                if not os.path.lexists(rec["root"]):
                    run = f"run ./install.sh --home {shlex.quote(name + '=' + rec['root'])}"
                elif variable and Path(rec["root"]) != harness.roots(
                        h.home, {k: v for k, v in env.items() if k != variable})[name]:
                    run = f"run {variable}={shlex.quote(str(rec['root']))} ./install.sh"
                else:
                    run = "run ./install.sh"
                fix = f"{run} in your Mifal clone"
                if w.warn:
                    fix = (f"{run} --overwrite-edits in your Mifal clone; {harness.TITLES[name]} then reads "
                           f"{show(w.rules)}, not {show(harness.reads_now(name, h.home, env, Path(rec['root'])))}")
                r.line("WARN", f"guide {name}", f"found at {show(Path(rec['root']))}, not served", fix)
            continue
        rules, root = Path(rec["rules"]), Path(rec["root"])
        _guide(r, name, rules, root, blocks.get(rec["rules"]), guide_sha, h, env)
        if name == "claude":
            def exact(n):
                return os.path.islink(root / "skills" / n) and os.readlink(root / "skills" / n) == str(h.pool / n)

            def resolves(n):
                link = root / "skills" / n
                return os.path.islink(link) and os.path.realpath(link) == os.path.realpath(h.pool / n)

            # Uninstall matches the recorded link text, so Mifal's own links must match exactly; a link of yours only has to work.
            wrong = [n for n in skills if n in mifal_skills and not exact(n)]
            yours = [n for n in skills if n not in mifal_skills and not resolves(n)]
            if wrong:
                r.line("FAIL", "skills claude", f"{len(wrong)} skill link(s) missing or changed in "
                       f"{show(root / 'skills')}: " + ", ".join(wrong[:5]), REINSTALL)
            else:
                r.line("PASS", "skills claude", f"{len(skills) - len(yours)} links in {show(root / 'skills')}")
            if yours:
                r.line("WARN", "your skills claude", f"{len(yours)} skill(s) of your own in {show(h.pool)} are not "
                       f"linked into {show(root / 'skills')}, so Claude Code does not see them: " + ", ".join(yours[:5]),
                       f"ln -s {show(h.pool)}/{yours[0]} {show(root / 'skills')}/{yours[0]}")
    _elsewhere(r, h, data, shell)
    _readers(r, h, data, shell)

    try:
        path, validator = _validator(h)
    except (OSError, SyntaxError) as e:
        r.line("FAIL", "validator", f"cannot load the contract validator ({e})", REINSTALL)
    else:
        run = subprocess.run([sys.executable, "-B", "-I", str(path), "selfcheck"], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, timeout=120)
        if run.returncode == 0:
            r.line("PASS", "validator", "selfcheck passed")
        else:
            r.line("FAIL", "validator", "selfcheck failed: " + (run.stdout + run.stderr).strip().splitlines()[-1],
                   REINSTALL)
        errors = validator.workflow_map_errors(h.pool, lambda p: Path(p).read_text(encoding="utf-8"))
        if errors:
            r.line("FAIL", "ask-matt pin", errors[0],
                   "restore ~/.agents/skills/ask-matt/SKILL.md: " + REINSTALL)
        else:
            r.line("PASS", "ask-matt pin", "the workflow map matches the installed Ask Matt body")

    _herdr(r, h)
    if shutil.which("agent-browser"):
        r.line("PASS", "agent-browser", "the agent-browser skill's CLI is on PATH")
    else:
        r.line("WARN", "agent-browser", "the agent-browser skill's CLI is not on PATH, and Mifal does not install it; "
               "browser checks need it", "npm i -g agent-browser && agent-browser install")

    if shell.get("FACTORY_HOME_OVERRIDE"):
        r.line("WARN", "droid", "FACTORY_HOME_OVERRIDE is set; Droid may not read the wiring in ~/.factory")
    for variable in ROOT_VARIABLES:
        value = shell.get(variable)
        if value and os.path.isabs(value) and not (os.path.realpath(value) + os.sep).startswith(str(h.real) + os.sep):
            out(f"WARN {variable} is {value}, outside your home folder")
            r.counts["WARN"] += 1

    out(f"doctor: {r.counts['PASS']} passed, {r.counts['WARN']} warning(s), {r.counts['FAIL']} failed")
    return 1 if r.counts["FAIL"] else 0


def _elsewhere(r, h, data, shell):
    """Agents found on this machine that the install does not serve, and a Claude home that shares a served one's
    skills and is not served itself."""
    show = h.show
    try:
        for line in harness.unserved(h.home, data, shell, show, unrecorded_only=True):
            r.out(line)
        homes = {harness.roots(h.home, e)["claude"] for e in (shell, {})}
    except harness.Refused as e:
        r.line("WARN", "agents", f"cannot look for agents or Claude homes Mifal does not serve: {e}")
        return
    recs = [r for r in (data.get("harnesses") or {}).get("claude", []) if r["status"] == "wired"]
    if not recs:
        return
    served = {os.path.realpath(Path(r["root"])) for r in recs}
    shared = {os.path.realpath(Path(r["root"]) / "skills") for r in recs}
    for other in sorted(homes):
        real = os.path.realpath(other / "skills")
        if os.path.realpath(other) not in served and real in shared:
            r.out(f"note also seen by {show(other)}: it shares {show(real)}, but Mifal does not serve "
                  f"{show(other)}, so the Guide reaches it only if its own rules file brings it in")


def _reads(home: Path, rules: Path) -> set:
    """The realpaths a rules file brings in: its link target, or each whole `@PATH` line outside a code fence."""
    if rules.is_symlink():
        return {os.path.realpath(rules)}
    try:
        text = rules.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    found, fence = set(), None
    for line in text.splitlines():
        if fence:
            # A fence ends at a line of the same character, at least as long as the opener, and nothing else.
            if re.fullmatch(" {0,3}" + re.escape(fence[0]) + "{%d,}[ \\t]*" % len(fence), line):
                fence = None
        elif opens := re.match(r" {0,3}(`{3,}(?=[^`]*$)|~{3,})", line):
            fence = opens.group(1)
        elif line.strip().startswith("@"):
            path = line.strip()[1:]
            path = str(home) + path[1:] if path.startswith("~/") else path
            if os.path.isabs(path):
                found.add(os.path.realpath(path))
    return found


def _readers(r, h, data, shell):
    """One note per folder directly under HOME or the XDG config folder, served by no recorded Home, whose rules file
    reads a shared file a recorded Home reads. Only AGENTS.md and CLAUDE.md files are opened."""
    recorded = [rec for _, rec in mf.homes(data)]
    served = {os.path.realpath(rec["root"]) for rec in recorded}
    shared = set().union(*(_reads(h.home, Path(rec["rules"])) for rec in recorded))
    shared.discard(os.path.realpath(h.engine / "AGENTS.md"))
    if not shared:
        return
    bases = [h.home]
    try:
        bases.append(harness.config_home(h.home, shell))
    except harness.Refused:
        pass
    seen = set()
    for base in bases:
        folders = sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
        for folder in folders:
            if os.path.realpath(folder) in served:
                continue
            reads = set()
            for name in ("AGENTS.md", "CLAUDE.md"):
                rules = folder / name
                if rules.is_symlink() or rules.is_file() and os.path.realpath(rules) not in shared:
                    reads |= _reads(h.home, rules) & shared
            for path in sorted(reads):
                if (os.path.realpath(folder), path) in seen:
                    continue
                seen.add((os.path.realpath(folder), path))
                r.out(f"note {h.show(folder)} reads {h.show(path)}, not served by this install")


def _guide(r, name, rules: Path, root: Path, entry, guide_sha, h, env):
    show, check = h.show, f"guide {name}"
    now = harness.reads_now(name, h.home, env, root)
    if now is not None and now != rules:
        w = harness.plan(name, h.home, env, root, show)
        r.line("FAIL", check, f"{harness.TITLES[name]} reads {show(now)}, not {show(rules)}",
               (w.skip or "").split(". ", 1)[-1] or REINSTALL)
        return
    text = rules.read_text(encoding="utf-8") if rules.is_file() else ""
    found = harness.BLOCK.findall(text)
    if entry is None or [b for b in found if harness.digest(b) == entry["sha256"]] == []:
        r.line("FAIL", check, f"the Mifal block in {show(rules)} is missing or edited",
               f"restore it: {REINSTALL}")
        return
    if f"guide=sha256:{guide_sha}" not in found[0].splitlines()[0]:
        r.line("FAIL", check, f"the block in {show(rules)} carries another Guide than {show(h.engine / 'AGENTS.md')}",
               REINSTALL)
        return
    if name == "codex" and len(text.encode("utf-8")) > 0.9 * harness.CODEX_CAP:
        r.line("WARN", check, f"{show(rules)} is {len(text.encode('utf-8'))} bytes, near Codex's 32 KiB default cap")
        return
    r.line("PASS", check, f"block in {show(rules)}")


def _key(r, rec, entry, guide_sha, h):
    """Option C: the owned block's bytes against the record, never a claim that a session loaded it, and the
    Home's hooks.json read again as data. No config value or hook command is printed."""
    show, check = h.show, "guide codex"
    root, config = Path(rec["root"]), Path(rec["config"])
    status, reason, _ = cc.hooks(root, cc.spellings(h), show)
    if rec["status"] == "pending":
        if status == "unknown":
            r.line("FAIL", check, f"{show(root)} is pending: {reason}", f"make {show(root / 'hooks.json')} a "
                   "regular file in the JSON shape Codex reads, then run mifal update")
        elif status == "pending":
            r.line("WARN", check, f"{show(root)} is pending: {reason}",
                   "Mifal never edits your hook; once its SessionStart hooks are gone, run mifal update")
        else:
            r.line("WARN", check, f"{show(root)} is pending, and nothing in its hooks.json stops the key now",
                   "run mifal update to add it")
        return
    if state(config) == mf.MISSING:
        r.line("FAIL", check, f"{show(config)} is missing", f"restore it: {REINSTALL}")
        return
    try:
        text = cc.read(config) if state(config)[0] == "file" else None
        if text is not None:
            cc.parse(text)
    except (cc.Invalid, OSError):
        r.line("FAIL", check, f"{show(config)} is not UTF-8 TOML any more",
               f"fix it so Codex can read it, then {REINSTALL}")
        return
    found = cc.split(text, entry["sha256"]) if text is not None and entry else None
    if found is None:
        r.line("FAIL", check, f"the Mifal {cc.KEY} key in {show(config)} is missing or edited",
               f"restore it: {REINSTALL}")
        return
    if f"guide=sha256:{guide_sha}" not in found[0].splitlines()[0]:
        r.line("FAIL", check, f"the key in {show(config)} carries another Guide than {show(h.engine / 'AGENTS.md')}",
               REINSTALL)
        return
    if status == "unknown":
        r.line("FAIL", check, f"{reason}, beside Mifal's {cc.KEY} key in {show(config)}",
               f"make {show(root / 'hooks.json')} a regular file in the JSON shape Codex reads")
    elif status == "pending":
        r.line("WARN", check, f"{show(root / 'hooks.json')} has a SessionStart hook beside Mifal's {cc.KEY} key in "
               f"{show(config)}", "remove the hook, or run mifal uninstall to remove the key; the next install or "
               "update holds until one of them goes")
    else:
        r.line("PASS", check, f"Mifal's {cc.KEY} key in {show(config)}, as installed")


def _herdr(r, h):
    show = h.show
    req = herdr.check()
    if req.status == "missing":
        r.line("FAIL", "herdr", "not found on PATH", "install it with `brew install herdr`, or run ./install.sh again")
        return
    if req.status == "old":
        r.line("FAIL", "herdr", f"{'.'.join(map(str, req.version))} is older than "
               f"{'.'.join(map(str, herdr.MINIMUM))}", herdr.upgrade_command(req.path))
        return
    if req.status != "ok":
        r.line("FAIL", "herdr", f"{show(req.path)} does not report a Herdr version",
               "move it aside or fix it, then run ./install.sh again")
        return
    version = ".".join(map(str, req.version))
    try:
        status = subprocess.run([req.path, "status", "--json"], capture_output=True, text=True,
                                stdin=subprocess.DEVNULL, timeout=10)
        server = json.loads(status.stdout).get("server", {})
    except (OSError, ValueError, subprocess.TimeoutExpired):
        server = {}
    if server.get("running"):
        r.line("PASS", "herdr", f"{version}, server {server.get('version')}")
    else:
        r.line("PASS", "herdr", f"{version}, server not running")
        r.line("WARN", "herdr server", "not running; start Herdr with `herdr` when you want a team")
    _protocol(r, req.path, h.engine / "tools" / "herdr_adapter" / "api-schema.json")


def _protocol(r, path, adapter_schema: Path):
    """Herdr's bundled socket schema against the one the team lead's adapter was built for."""
    check = "herdr protocol"
    try:
        theirs = json.loads(subprocess.run([path, "api", "schema", "--json"], capture_output=True, text=True,
                                           stdin=subprocess.DEVNULL, timeout=10).stdout)
        ours = json.loads(adapter_schema.read_text(encoding="utf-8"))
        if not isinstance(theirs, dict) or not isinstance(ours, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        r.line("WARN", check, "could not compare `herdr api schema --json` with the adapter's schema; "
               "the team lead may not work with this Herdr")
        return
    if theirs.get("protocol") != ours.get("protocol"):
        r.line("WARN", check, f"Herdr speaks protocol {theirs.get('protocol')}, the team lead's experimental "
               f"adapter speaks protocol {ours.get('protocol')} and refuses this Herdr; the team lead's raw "
               "`herdr` commands still work, and `mifal update` brings an adapter built for it once released")
    elif theirs != ours:
        r.line("WARN", check, f"{ours.get('protocol')}, but its schema differs from the one the adapter was "
               "built for; run `mifal update`, and report a team-mode failure if you see one")
    else:
        r.line("PASS", check, f"{ours.get('protocol')}, the schema the team lead's adapter speaks")
