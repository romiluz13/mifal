"""mifal: install, uninstall and inspect a Mifal install."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import doctor
from . import harness
from . import herdr
from . import install as inst
from . import journal
from . import manifest as mf
from . import uninstall as uninst
from . import update as upd

ROOT = Path(__file__).resolve().parents[2]


def version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _parser():
    p = argparse.ArgumentParser(prog="mifal")
    sub = p.add_subparsers(dest="command", required=True)
    i = sub.add_parser("install", help="install or reinstall from this clone")
    i.add_argument("--dry-run", action="store_true", help="print every write, change nothing")
    i.add_argument("--herdr-script", action="store_true",
                   help="without Homebrew, install Herdr with its official script without asking")
    i.add_argument("--overwrite-edits", action="store_true",
                   help="save a copy of each file you changed since Mifal wrote it, then replace it")
    i.add_argument("--harness", action="append", choices=harness.NAMES, metavar="NAME",
                   help="wire only this harness (repeatable): " + ", ".join(harness.NAMES))
    i.add_argument("--home", action="append", metavar="NAME=PATH",
                   help="serve this Home of a harness (repeatable); for a harness named here, only its named Homes "
                        "are served")
    i.add_argument("--allow-root-outside-home", action="store_true",
                   help="write into a folder whose realpath lies outside your home folder")
    u = sub.add_parser("uninstall", help="remove everything the install wrote and restore what it displaced")
    u.add_argument("--dry-run", action="store_true", help="print what would be removed or restored")
    up = sub.add_parser("update", help="fetch in the recorded clone, preview the new revision, then install it")
    up.add_argument("--yes", action="store_true", help="apply without asking")
    up.add_argument("--branch", action="store_true",
                    help="follow the clone's recorded upstream branch instead of the newest release tag")
    up.add_argument("--overwrite-edits", action="store_true",
                    help="save a copy of each file you changed since Mifal wrote it, then replace it")
    sub.add_parser("doctor", help="check the install; read-only")
    sub.add_parser("version", help="print the installed version")
    return p


def _out(line):
    print(line, flush=True)


def _err(line):
    print(line, file=sys.stderr, flush=True)


def _interrupted(h, dry_run):
    """The Manifest's data after rolling back an interrupted install, or the Manifest as it is."""
    loaded = mf.load(h)
    if loaded is None or loaded[0].get("state") != "installing":
        return loaded[0] if loaded else None
    data = loaded[0]
    moved = inst.moved_folders(h, data.get("folders", {}))
    if moved:
        print("An interrupted install was found, but folders it wrote into have moved since:")
        for line in moved:
            print(line)
        print("Nothing was rolled back. Put those folders back where they were, then run mifal again.")
        raise SystemExit(1)
    print("An interrupted install was found. " + ("It would be rolled back first:" if dry_run else "Rolling it back:"))
    journal.rollback(h, data, journal.Fs(dry_run, print))
    note = journal.update_note(data)
    if note:
        print(note)
    return mf.migrate(h, json.loads(data["previous"])) if data["previous"] is not None else None


def _refused(plan) -> bool:
    if not (plan.conflicts or plan.stops):
        return False
    for line in plan.stops:
        print(line)
    if plan.conflicts:
        hard = {line for line, *_ in plan.unwritable} | set(plan.held)
        held = {line for line, *_ in plan.fallbacks}
        soft = [line for line in plan.conflicts if line not in hard and line not in held]
        if soft or hard:
            print("These paths changed since Mifal wrote them, or are not Mifal's:" if soft else
                  "Mifal cannot write these rules files:" if plan.unwritable else "Mifal cannot write these files:")
        for line in plan.conflicts:
            print(f"  {line}" if line not in held else line)
        if plan.unwritable:
            for line in inst.unwritable_advice(plan, True):
                print(line)
        if soft:
            print("Move them aside, or run again with --overwrite-edits to save a copy of each first.")
        for line in inst.fallback_advice(plan, "Run again with --overwrite-edits"):
            print(line)
    print("Nothing was written.")
    return True


def _named(h, values):
    """The Homes given with --home NAME=PATH, by Harness, or None after saying why one cannot be used."""
    named = {}
    for value in values or []:
        name, sep, path = value.partition("=")
        if path == "~" or path.startswith("~/"):
            path = str(h.home) + path[1:]
        if not sep:
            why = "write it as NAME=PATH, such as codex=$HOME/.codex-work"
        elif name not in harness.NAMES:
            why = "NAME must be one of " + ", ".join(harness.NAMES)
        elif not os.path.isabs(path):
            why = f"PATH must be absolute, such as {name}=$HOME/.{name}-work"
        else:
            named.setdefault(name, []).append(Path(path))
            continue
        print(f"mifal: --home {value}: {why}. Nothing was written.")
        return None
    return named


def _plan(h, args, named):
    try:
        return inst.make_plan(h, ROOT, version(), args.overwrite_edits, args.harness, os.environ,
                              args.allow_root_outside_home, named=named,
                              linked={os.path.realpath(p) for p in named.get("codex", [])})
    except harness.Refused as e:
        print(e)
        return None


def _summary(h, plan):
    """A first install's lines: notes and every step outside Mifal's own files in full, Mifal's own files counted."""
    yield from plan.notes
    files, skills, links = 0, set(), {}
    for step in plan.steps:
        path = Path(step.op.get("path", ""))
        if step.op["op"] == "write" and h.pool in path.parents:
            skills.add(path.relative_to(h.pool).parts[0])
        elif step.op["op"] == "write" and h.engine in path.parents:
            files += 1
        elif step.op["op"] == "link" and path != h.link:
            links[path.parent] = links.get(path.parent, 0) + 1
        elif step.op["op"] not in ("write", "link", "mkdir", "block") and step.line:
            yield step.line
    yield f"{h.show(h.engine)}: the engine, {files} files"
    yield f"{h.show(h.pool)}: {len(skills)} skills"
    for folder, count in links.items():
        yield f"{h.show(folder)}: {count} links"
    for step in plan.steps:
        if step.op["op"] == "block":
            yield step.line
    wired = [harness.TITLES[n] for n in harness.NAMES
             if any(r["status"] == "wired" for r in plan.data["harnesses"].get(n, []))]
    yield f"Wired: {', '.join(wired) or 'none'}"
    pending = [f"{harness.TITLES[n]} at {h.show(r['root'])}" for n in harness.NAMES
               for r in plan.data["harnesses"].get(n, []) if r["status"] == "pending"]
    if pending:
        yield "Pending, not served until their hooks allow it: " + ", ".join(pending)


def main(argv) -> int:
    args = _parser().parse_args(argv)
    h = mf.Home(Path.home())
    if args.command == "version":
        print(f"mifal {version()}")
        return 0
    if args.command == "doctor":
        return doctor.doctor(h, os.environ, _out)
    if args.command != "install" and not getattr(args, "dry_run", False):
        journal.tidy(h)
    if args.command == "update":
        loaded = mf.load(h)
        if loaded is None:
            print(f"mifal: no Manifest at {h.show(h.manifest)}; install Mifal first.")
            return 1
        if loaded[0]["state"] == "installing":
            _interrupted(h, False)
            print("Rolled back. Run mifal update again to see the update.")
            return 1
        return upd.update(h, loaded[0], args, _out)
    if args.command == "uninstall":
        if mf.load(h) is None:
            print(f"mifal: no Manifest at {h.show(h.manifest)}; nothing to uninstall.")
            return 1
        data = _interrupted(h, args.dry_run)
        return uninst.uninstall(h, data, journal.Fs(args.dry_run, print)) if data else 0
    if not ((ROOT / "skills").is_dir() and (ROOT / "install.sh").is_file()):
        print("mifal: install runs from a Mifal clone; run ./install.sh there.")
        return 1
    named = _named(h, args.home)
    if named is None:
        return 1
    refusal = inst.refuse_older_clone(h, ROOT)
    if refusal:
        print(refusal)
        return 1
    if not args.dry_run:
        journal.tidy(h)
    loaded = mf.load(h)
    if loaded and loaded[0]["state"] == "installing":
        _interrupted(h, args.dry_run)
        if args.dry_run:
            print("Dry run: nothing written. Run the installer without --dry-run to roll back, then see the plan.")
            return 0
        if not sys.stdin.isatty():
            print("Rolled back. Run the installer again to install.")
            return 1
        if input("Rolled back. Continue with the install? [y/N] ").strip().lower() not in ("y", "yes"):
            return 1
    plan = _plan(h, args, named)
    if plan is None or _refused(plan):
        return 1
    record = herdr.ensure(args.herdr_script, args.dry_run, _out, _err,
                          previous=plan.data["dependencies"].get("herdr"), show=h.show)
    if record is None:
        return 1
    if not args.dry_run:
        plan = _plan(h, args, named)
        if plan is None or _refused(plan):
            return 1
        plan.data["dependencies"] = dict(plan.data["dependencies"], herdr=record)
    lines = list(plan.lines())
    if not (plan.steps or plan.changes_manifest):
        for line in plan.notes:
            print(line)
        print("Nothing to change: Mifal is installed and current.")
        return 0
    first = plan.old is None and not args.dry_run
    for line in _summary(h, plan) if first else lines:
        print(line)
    if args.dry_run:
        print(f"Dry run: {len(lines)} line(s), nothing written.")
        return 0
    try:
        journal.run(plan, _out)
    except Exception as e:
        print(f"mifal: install failed ({e}); rolled back.")
        return 1
    print(f"Installed Mifal {version()}: {len(lines)} change(s).")
    bindir = str(h.home / ".local" / "bin")
    if bindir not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"Add {bindir} to your PATH to run mifal, for example: echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.zprofile")
    if first:
        print("Next: run `mifal doctor`, then start a session in any wired agent and ask for engineering work.")
    return 0
