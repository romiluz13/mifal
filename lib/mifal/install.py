"""Plan an install. The plan is the single source of the dry run, the journal and the writes."""
from __future__ import annotations

import itertools
import os
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import harness
from . import manifest as mf
from .journal import TXN
from .manifest import MISSING, Home, expected, sha256_file, state

ENGINE_SOURCES = ("bin", "lib", "tools", "LICENSE", "NOTICE", "VERSION", "third_party")
IGNORED = {"__pycache__", ".DS_Store"}
OWNED = ("file", "dir", "symlink")
CARRIED = ("backup", "saved")


@dataclass
class Step:
    op: dict
    line: str | None = None
    src: Path | None = None
    content: str | None = None


@dataclass
class Plan:
    home: Home
    steps: list = field(default_factory=list)
    pre: int = 0
    notes: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    stops: list = field(default_factory=list)
    unwritable: list = field(default_factory=list)
    leave_out: list = field(default_factory=list)
    data: dict = field(default_factory=dict)
    previous: str | None = None
    old: dict | None = None

    @property
    def changes_manifest(self) -> bool:
        return bool(self.steps) or self.old is None or any(
            self.old.get(k) != self.data.get(k) for k in ("version", "home", "source", "entries", "dependencies", "harnesses", "folders"))

    def lines(self):
        yield from self.notes
        for step in self.steps:
            if step.line:
                yield step.line
        if self.changes_manifest:
            verb = "update" if self.previous is not None else "create"
            yield f"{verb} {self.home.show(self.home.manifest)}"


def source_files(h: Home, source: Path):
    """(target realpath, source file) for every file Mifal installs."""
    for name in ENGINE_SOURCES:
        yield from _walk(source / name, h.engine / name)
    yield h.engine / "AGENTS.md", source / "guide" / "AGENTS.md"
    for skill in sorted(p for p in (source / "skills").iterdir() if p.is_dir() and p.name not in IGNORED):
        yield from _walk(skill, h.pool / skill.name)


SEMVER = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$", re.ASCII)


def last_committed_version(data: dict):
    """The version of the last completed install: the Manifest's own, or, while an install or update is pending, the
    one inside its previous record. None when there is none to compare with."""
    if data.get("state") != "installing":
        return data.get("version")
    try:
        previous = json.loads(data["previous"]) if data.get("previous") is not None else None
    except (ValueError, TypeError):
        return None
    return previous.get("version") if isinstance(previous, dict) else None


def refuse_older_clone(h: Home, source: Path):
    """The message that stops an install from a clone older than the last completed install, or None. Read-only, so
    it runs before tidy or any rollback."""
    loaded = mf.load(h)
    if loaded is None:
        return None
    installed = last_committed_version(loaded[0])
    have = SEMVER.match(installed) if isinstance(installed, str) else None
    if not have:
        return None
    try:
        text = (source / "VERSION").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return f"mifal: {source} has no readable VERSION file, so Mifal cannot tell whether installing it would downgrade. Nothing was changed."
    clone = SEMVER.match(text)
    if not clone:
        return f"mifal: the VERSION of {source} ({text!r}) is not X.Y.Z, so Mifal cannot tell whether installing it would downgrade. Nothing was changed."
    if tuple(map(int, clone.groups())) < tuple(map(int, have.groups())):
        pending = (f"\nAn interrupted install or update is pending; `mifal update`, or an install from a clone of {installed} or newer, rolls it back."
                   if loaded[0].get("state") == "installing" else "")
        return (f"mifal: this clone is Mifal {text}, older than the Mifal {installed} installed here. Nothing was changed.\n"
                f"To move to the newest release, run `mifal update`, or install from a clone of {installed} or newer. "
                "To install the older version on purpose, run `mifal uninstall` first." + pending)
    return None


class Unreadable(Exception):
    """The recorded revision's file list cannot be read."""


def engine_missing(h: Home, data: dict) -> list:
    """Install targets of the engine source files of the recorded revision that the Manifest does not own, read
    with one local `git ls-tree` of that revision: no fetch, no network, nothing written."""
    source = data.get("source") or {}
    clone, rev = source.get("path"), source.get("revision")
    if not clone or not rev:
        raise Unreadable("the Manifest records no clone or revision")
    if not (Path(clone) / ".git").exists():
        raise Unreadable(f"the clone {clone} is gone")
    try:
        run = subprocess.run(["git", "-C", clone, "ls-tree", "-r", "-z", "--name-only", rev], capture_output=True,
                             text=True, stdin=subprocess.DEVNULL, timeout=30,
                             env={**os.environ, "GIT_NO_LAZY_FETCH": "1"})  # a partial clone must not fetch here
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Unreadable(f"git could not list {rev[:12]} ({e})")
    names = [n for n in run.stdout.split("\0") if n]
    if run.returncode != 0 or not names:
        raise Unreadable(f"git could not list the files of revision {rev[:12]} in {clone}")
    # Entries are matched by their place under the engine folder as recorded, so a differently spelled HOME on a
    # case-insensitive volume does not make every file look missing.
    base = ((data.get("folders") or {}).get("engine") or {}).get("real") or str(h.engine)
    prefix = base.rstrip(os.sep) + os.sep
    owned = {e["path"][len(prefix):] for e in data["entries"] if e["kind"] in OWNED and e["path"].startswith(prefix)}
    wanted = [n for n in names if n.split("/", 1)[0] in ENGINE_SOURCES and not IGNORED.intersection(n.split("/"))]
    return [str(h.engine / n) for n in wanted if n not in owned]


def _walk(src: Path, target: Path):
    if src.is_file():
        yield target, src
        return
    for root, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED)
        for name in sorted(files):
            if name in IGNORED:
                continue
            path = Path(root, name)
            yield target / path.relative_to(src), path


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _git_out(source: Path, *args):
    result = subprocess.run(["git", "-C", str(source), *args], capture_output=True, text=True,
                            stdin=subprocess.DEVNULL)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def source_info(source: Path) -> dict:
    """The clone an install comes from: its path, revision, upstream branch and that remote's URL."""
    if not (source / ".git").exists():
        return {"path": str(source), "revision": None}
    upstream = _git_out(source, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    url = _git_out(source, "remote", "get-url", upstream.split("/", 1)[0]) if upstream else None
    return {"path": str(source), "revision": _git_out(source, "rev-parse", "HEAD"), "upstream": upstream, "url": url}


def _depth(path: Path):
    return (len(path.parts), str(path))


def folders(h: Home, found_roots: dict, names) -> dict:
    """Each folder Mifal writes into: its path as the user names it, and its realpath now."""
    named = {"engine": h.home / mf.ENGINE, "pool": h.home / mf.POOL, "bin": h.home / mf.BIN}
    named.update({"harness:" + n: found_roots[n] for n in names})
    return {k: {"path": str(p), "real": os.path.realpath(p)} for k, p in named.items()}


def moved_folders(h: Home, recorded: dict) -> list:
    """A line for each recorded folder whose realpath changed since install."""
    lines = []
    for key, f in sorted(recorded.items()):
        now = os.path.realpath(f["path"])
        if now != f["real"]:
            lines.append(f"{h.show(f['path'])} now resolves to {h.show(now)}, not {h.show(f['real'])} as installed")
    return lines


def linked_folder(h: Home, folder: Path):
    """How to treat a skills folder that is a symlink: ("ok", target), ("outside", target) or ("refuse", why).

    Only a link that leads straight to a real folder is written through. A dangling link, a link to a file or to
    another link, and a path through a symlinked folder inside the home are refused: none is a folder the person
    plainly means Mifal to write into."""
    target = Path(os.path.normpath(os.path.join(folder.parent, os.readlink(folder))))
    if not os.path.lexists(target):
        return "refuse", "which does not exist", target
    if target.is_symlink():
        return "refuse", "which is itself a link", target
    if not target.is_dir():
        return "refuse", "which is not a folder", target
    for parent in target.parents:
        if parent not in (h.home, h.real) and (_inside(parent, h.home) or _inside(parent, h.real)) and parent.is_symlink():
            return "refuse", f"which lies behind the link {h.show(parent)}", target
    return ("ok" if _inside(Path(os.path.realpath(target)), h.real) else "outside"), None, target


def make_plan(h: Home, source: Path, version: str, overwrite_edits: bool = False, selected=None, env=None,
              allow_outside: bool = False, source_record=None) -> Plan:
    loaded = mf.load(h)
    old, previous = loaded if loaded else (None, None)
    if old is None and os.path.lexists(h.engine):
        raise SystemExit(f"mifal: {h.show(h.engine)} exists but holds no Manifest. Move it aside and run the installer again.")
    if old and old.get("state") != "complete":
        raise SystemExit("mifal: an interrupted install must be rolled back first; run the installer again.")
    owned = {Path(e["path"]): e for e in old["entries"] if e["kind"] in OWNED} if old else {}
    old_blocks = {Path(e["path"]): e for e in old["entries"] if e["kind"] == "block"} if old else {}
    entries = [e for e in old["entries"] if e["kind"] in CARRIED] if old else []
    plan = Plan(h, previous=previous, old=old)
    show = h.show
    env = os.environ if env is None else env

    found_roots = harness.roots(h.home, env)
    was_wired = [n for n, r in (old or {}).get("harnesses", {}).items() if r["status"] == "wired"]
    names = [n for n in harness.NAMES if n in set(harness.detect(h.home, env, found_roots) if selected is None else selected) | set(was_wired)]
    now_folders = folders(h, found_roots, names)
    plan.stops += moved_folders(h, {k: f for k, f in (old or {}).get("folders", {}).items() if k in now_folders})
    for key, f in now_folders.items():
        if not allow_outside and not _inside(Path(f["real"]), h.real):
            plan.stops.append(f"{show(f['path'])} resolves to {f['real']}, outside your home folder. "
                              "Run with --allow-root-outside-home to write there.")
    wirings = [harness.plan(n, h.home, env, Path(now_folders["harness:" + n]["real"]), show) for n in names]
    guide_text = (source / "guide" / "AGENTS.md").read_text(encoding="utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stash_names = itertools.count()
    files = dict(source_files(h, source))
    link_target = str(h.engine / "bin" / "mifal")
    skills = sorted({t.relative_to(h.pool).parts[0] for t in files if _inside(t, h.pool)})
    skill_links = {w.root / "skills" / name: str(h.pool / name)
                   for w in wirings if w.mode == "import" and (not w.skip or w.rules in old_blocks) for name in skills}
    units = [h.pool / name for name in skills] + [h.link] + sorted(skill_links)

    for folder, real in h.linked():
        plan.notes.append(f"note {show(folder)} is a link to {show(real)}; Mifal writes there")

    through = set()
    for w in wirings:
        folder = w.root / "skills"
        if not (w.mode == "import" and (not w.skip or w.rules in old_blocks) and folder.is_symlink()):
            continue
        through.add(folder)
        verdict, why, target = linked_folder(h, folder)
        if verdict == "refuse":
            plan.stops.append(
                f"{show(folder)} is a link to {os.readlink(folder)}, {why}. Mifal writes into a skills folder behind "
                f"a link only when the link leads straight to a real folder in your home. Point the link at one, or "
                f"leave {harness.TITLES[w.name]} out with --harness and name the other agents.")
        elif verdict == "outside" and not allow_outside:
            plan.stops.append(f"{show(folder)} is a link to {target}, outside your home folder. "
                              "Run with --allow-root-outside-home to write there.")
        else:
            plan.notes.append(f"note {show(folder)} is a link to {show(target)}; Mifal writes there")
            shared = {Path(r[w.name]) for r in (harness.roots(h.home, env), harness.roots(h.home, {}))}
            for other in sorted(shared):
                if (os.path.realpath(other) != str(w.root) and os.path.isdir(other / "skills")
                        and os.path.realpath(other / "skills") == os.path.realpath(folder)):
                    plan.notes.append(f"note also seen by {show(other)}: it shares {show(target)}")

    moves, gone = [], []

    def move(path, dest, line, why):
        moves.append(Step({"op": "move", "from": str(path), "to": str(dest), "why": why}, line))
        gone.append(path)

    def vanishes(path):
        return any(_inside(path, g) for g in gone)

    def stash(path, line=None):
        move(path, h.engine / TXN / str(next(stash_names)), line, "stash")

    def conflict(path, reason):
        if overwrite_edits:
            dest = h.under(h.saved / stamp, path)
            move(path, dest, f"save {show(path)} -> {show(dest)}", "save")
            entries.append({"kind": "saved", "path": str(dest), "original": str(path)})
        else:
            plan.conflicts.append(f"{show(path)}: {reason}")

    def claim(path, want):
        """The verb for making path hold want, after moving aside what is there, or None when it already does."""
        if vanishes(path):
            return "create"
        now = state(path)
        if now == want:
            return None
        if now == MISSING:
            return "create"
        entry = owned.get(path)
        if entry and now == expected(entry):
            stash(path)
        else:
            conflict(path, "changed since Mifal wrote it" if entry else "exists and was not installed by Mifal")
        return "update"

    for unit in units:
        if os.path.lexists(unit) and not any(_inside(p, unit) for p in owned):
            dest = h.under(h.engine / "backup" / stamp, unit)
            move(unit, dest, f"backup {show(unit)} -> {show(dest)}", "backup")
            entries.append({"kind": "backup", "path": str(unit), "backup": str(dest)})

    writes, links = [], []
    for target, src in files.items():
        digest = sha256_file(src)
        verb = claim(target, ("file", digest))
        if verb:
            writes.append(Step({"op": "write", "path": str(target), "sha256": digest}, f"{verb} {show(target)}", src))
        entries.append({"kind": "file", "path": str(target), "sha256": digest})
    for path, target in [(h.link, link_target)] + sorted(skill_links.items()):
        if claim(path, ("link", target)):
            links.append(Step({"op": "link", "path": str(path), "target": target}, f"link {show(path)} -> {target}"))
        entries.append({"kind": "symlink", "path": str(path), "target": target})

    blocks, records = [], {}
    for w in wirings:
        records[w.name] = {"root": str(w.root), "rules": str(w.rules), "status": "skipped" if w.skip else "wired"}
        rec = old_blocks.get(w.rules)
        if w.skip:
            plan.notes.append(w.skip)
            if rec:
                entries.append(rec)
                records[w.name]["status"] = "wired"
            continue
        new_block = harness.block(w.name, version, guide_text)
        if os.path.lexists(w.rules) and state(w.rules)[0] != "file":
            kind = state(w.rules)
            where = f"{show(w.rules)}: "
            if kind[0] == "link":
                dest = show(Path(kind[1])) if os.path.isabs(kind[1]) else kind[1]
                why = f"is a symbolic link to {dest}, and Mifal does not write through a link"
            elif kind[0] == "dir":
                why = "is a folder, and Mifal writes a file there"
            else:
                why = "is not a regular file"
            plan.conflicts.append(where + why)
            plan.unwritable.append((where + why, kind[0], w.name, dest if kind[0] == "link" else None))
            continue
        if w.warn:
            if old is None or overwrite_edits:
                plan.notes.append("note " + w.warn)
            else:
                plan.conflicts.append(w.warn)
        text = mf.read_rules(w.rules) if os.path.lexists(w.rules) else None
        found = harness.BLOCK.findall(text or "")
        sep, created, copy = (rec["sep"], rec["created"], None) if rec else (None, text is None, None)
        if rec and text is not None and (len(found) != 1 or harness.digest(found[0]) != rec["sha256"]):
            if not overwrite_edits or len(found) > 1:
                plan.conflicts.append(f"{show(w.rules)}: its Mifal block changed since install")
                entries.append(rec)
                continue
            dest = h.under(h.saved / stamp, w.rules)
            moves.append(Step({"op": "copy", "from": str(w.rules), "to": str(dest), "why": "save"},
                              f"save {show(w.rules)} -> {show(dest)}"))
            entries.append({"kind": "saved", "path": str(dest), "original": str(w.rules)})
        elif not rec and found:
            plan.conflicts.append(f"{show(w.rules)}: holds a Mifal block this install did not write")
            continue
        if found and found[0] == new_block and rec:
            entries.append(rec)
            continue
        if found and (rec or overwrite_edits):
            new_text, verb = text.replace(found[0], new_block, 1), "update"
        else:
            if sep is None or text is None:
                sep = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
            created = True if text is None else created
            new_text, verb = (text or "") + sep + new_block, "block"
        if w.name == "codex" and len(new_text.encode("utf-8")) > harness.CODEX_CAP:
            plan.notes.append(f"warn codex: {show(w.rules)} would be {len(new_text.encode('utf-8'))} bytes with the "
                              "Guide, past Codex's 32 KiB default cap, so Codex may cut it short.")
        if text is not None:
            copy = str(h.engine / TXN / str(next(stash_names)))
        blocks.append(Step({"op": "block", "path": str(w.rules), "sha256": harness.digest(new_text),
                            "before": harness.digest(text) if text is not None else None, "copy": copy},
                           f"{verb} {show(w.rules)}", content=new_text))
        entries.append({"kind": "block", "path": str(w.rules), "sha256": harness.digest(new_block),
                        "sep": sep, "created": created})

    recorded, transient = set(), set()

    def need(path, root, into):
        """Every folder from path up to root, and root's missing or Mifal-made ancestors."""
        while _inside(path, root):
            into.add(path)
            path = path.parent
        while path != path.parent and (not os.path.lexists(path) or path in owned):
            into.add(path)
            path = path.parent

    for target in files:
        need(target.parent, h.engine if _inside(target, h.engine) else h.pool / target.relative_to(h.pool).parts[0],
             recorded)
    need(h.link.parent, h.link, recorded)
    for path in skill_links:
        if path.parent not in through:
            need(path.parent, path.parent.parent, recorded)
    for step in blocks:
        rules = Path(step.op["path"])
        need(rules.parent, rules.parent, recorded)
    for step in list(moves):
        dest = Path(step.op["to"])
        if step.op["why"] == "backup":
            need(dest.parent, h.engine, recorded)
        elif step.op["why"] == "save":
            need(dest.parent, h.saved, transient)
    if writes or blocks:
        need(h.engine / TXN, h.engine / TXN, transient)

    removed, rmdirs = set(), []
    for path, entry in sorted(owned.items(), key=lambda kv: _depth(kv[0]), reverse=True):
        if path in files or path == h.link or path in skill_links or path in recorded:
            continue
        now = state(path)
        if now == MISSING:
            continue
        if entry["kind"] == "dir":
            if now == ("dir",) and all(c in removed for c in path.iterdir()):
                rmdirs.append(Step({"op": "rmdir", "path": str(path)}, f"remove {show(path)}"))
                removed.add(path)
            else:
                entries.append(entry)
        elif now == expected(entry):
            stash(path, f"remove {show(path)}")
            removed.add(path)
        else:
            plan.notes.append(f"keep {show(path)}: changed since install, and no longer part of Mifal")

    if any(s.op["why"] == "stash" for s in moves):
        need(h.engine / TXN, h.engine / TXN, transient)

    outer, inner = [], []
    for path in sorted(recorded | transient, key=_depth):
        if vanishes(path) or not os.path.lexists(path):
            (inner if vanishes(path) else outer).append(Step({"op": "mkdir", "path": str(path)},
                                                              None if path in transient and path.name == TXN
                                                              else f"create {show(path)}"))
        elif state(path) != ("dir",):
            conflict(path, "is not a folder")
            inner.append(Step({"op": "mkdir", "path": str(path)}, f"create {show(path)}"))
        if path in recorded and (vanishes(path) or not os.path.lexists(path) or path in owned):
            entries.append({"kind": "dir", "path": str(path)})

    first = [s for s in outer if _inside(h.engine, Path(s.op["path"]))]
    plan.steps = first + [s for s in outer if s not in first] + moves + inner + writes + links + blocks + rmdirs
    plan.pre = len(first)
    plan.data = {
        "format": mf.FORMAT,
        "state": "complete",
        "version": version,
        "home": str(h.real),
        "source": source_record or source_info(source),
        "entries": sorted(entries, key=lambda e: (e["kind"], e["path"])),
        "dependencies": old.get("dependencies", {}) if old else {},
        "harnesses": records,
        "folders": now_folders,
    }
    blocked = {u[2] for u in plan.unwritable}
    if not blocked & set(was_wired):
        plan.leave_out = [w.name for w in wirings if w.name not in blocked and not w.skip]
    return plan


def unwritable_advice(plan, can_leave_out: bool) -> list:
    """The ways out of a rules file Mifal will not write; saving a copy first does not apply to a link or a folder."""
    many = len(plan.unwritable) > 1
    links = [dest for _, kind, _, dest in plan.unwritable if kind == "link"]
    what = "each" if many else "the link" if links else "it"
    lines = [f"To wire {'these agents' if many else 'that agent'}, replace {what} with a regular file and run again"]
    if links:
        lines[0] += ("; each agent then reads its own copy, not the file its link pointed to." if many else
                     f"; the agent then reads its own copy, not {links[0]}.")
    else:
        lines[0] += "."
    if can_leave_out and plan.leave_out:
        lines.append("Or wire only the other agents: ./install.sh " + " ".join(f"--harness {n}" for n in plan.leave_out))
    return lines
