"""Run an install's steps under a journal, and roll back a failed or interrupted one.

The Manifest is the journal: it is written with state "installing", listing every step, before the first
backup or write, and replaced by the complete Manifest last. Every step is undone only when its effect is
still exactly what the step left, so a path changed since is kept and reported.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import manifest as mf
from .manifest import MISSING, state

TXN = ".txn"
FAIL_AT = "MIFAL_TEST_FAIL_AT"


class Fs:
    """Acts on the filesystem, or in a dry run only says what it would do, answering later checks as if it had."""

    def __init__(self, dry_run: bool, out):
        self.dry_run, self.out = dry_run, out
        self.gone, self.made = set(), set()

    def exists(self, path: Path) -> bool:
        if path in self.made:
            return True
        if path in self.gone or any(p in self.gone for p in path.parents):
            return False
        return os.path.lexists(path)

    def state(self, path: Path) -> tuple:
        return state(path) if self.exists(path) else MISSING

    def empty(self, path: Path) -> bool:
        children = set(path.iterdir()) if path.is_dir() and not path.is_symlink() else set()
        children |= {p for p in self.made if p.parent == path}
        return not any(self.exists(c) for c in children)

    def remove(self, path: Path, line=None):
        if line:
            self.out(line)
        if not self.dry_run:
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()
        self.gone.add(path)
        self.made.discard(path)

    def move(self, src: Path, dst: Path, line):
        self.out(line)
        if not self.dry_run:
            os.rename(src, dst)
        self.gone.add(src)
        self.made.discard(src)
        self._arrive(dst)

    def mkdir(self, path: Path, line):
        self.out(line)
        if not self.dry_run:
            path.mkdir()
        self._arrive(path)

    def _arrive(self, path: Path):
        """Something new is at path now, so nothing that left from there or below it counts any more."""
        self.gone = {g for g in self.gone if g != path and path not in g.parents}
        self.made.add(path)


def _fault(point: str) -> None:
    name, _, how = os.environ.get(FAIL_AT, "").partition(":")
    if name != point:
        return
    if how == "exit":
        os._exit(70)
    raise RuntimeError(f"injected failure at {point}")


def _do(step, tmp: Path) -> None:
    """Apply one step. tmp is this step's name in the journal's own .txn folder, so a temporary file there is
    provably Mifal's, and rollback removes it with the folder."""
    op = step.op
    kind = op["op"]
    if kind == "mkdir":
        Path(op["path"]).mkdir()
    elif kind == "move":
        os.rename(op["from"], op["to"])
    elif kind == "write":
        path = Path(op["path"])
        mf.replace_file(path, Path(step.src).read_bytes(), mf.mode_of(Path(step.src)), tmp)
    elif kind == "copy":
        shutil.copy2(op["from"], op["to"])
    elif kind == "block":
        path = Path(op["path"])
        if op["copy"]:
            shutil.copy2(path, op["copy"])
        mf.replace_file(path, step.content.encode("utf-8"), mf.mode_of(path), tmp)
    elif kind == "link":
        os.symlink(op["target"], op["path"])
    elif kind == "rmdir":
        os.rmdir(op["path"])


def run(plan, out, last=None, update=None) -> None:
    """Apply the plan. last, when given, is the final step before publication (an update's fast-forward);
    update records the clone's old and new SHAs in the journal, so a rollback can name them."""
    h = plan.home
    steps, pre = plan.steps, plan.pre
    tmps = [h.engine / TXN / f"{i}.tmp" for i in range(len(steps))]
    for step, tmp in zip(steps[:pre], tmps):
        _do(step, tmp)
    journal = dict(plan.data, state="installing", previous=plan.previous, steps=[s.op for s in steps], pre=pre)
    if update:
        journal["update"] = update
    mf.save(h, journal)
    moved = wrote = False
    try:
        for step, tmp in zip(steps[pre:], tmps[pre:]):
            _do(step, tmp)
            if step.op["op"] == "move" and not moved:
                moved = True
                _fault("after-backup")
            if step.op["op"] == "write" and not wrote:
                wrote = True
                _fault("after-write")
        _fault("before-publication")
        if last:
            _fault("fast-forward")
            last()
            _fault("after-fast-forward")
        mf.save(h, dict(plan.data, installed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    except BaseException:
        out("Install failed; rolling back:")
        rollback(h, journal, Fs(False, out))
        raise
    _fault("after-publication")
    tidy(h)


def tidy(h) -> None:
    """Remove what a committed install moved aside, if the process stopped before removing it.
    An install still in progress keeps it: its rollback restores from there. Without a Manifest the folder is not
    Mifal's to remove."""
    loaded = mf.load(h)
    if loaded is None or loaded[0].get("state") == "installing":
        return
    _remove_txn(h)


def _remove_txn(h) -> None:
    txn = h.engine / TXN
    if txn.is_dir() and not txn.is_symlink():
        shutil.rmtree(txn)


def update_note(journal: dict):
    """What an interrupted update left in the clone, or None."""
    u = journal.get("update")
    if not u:
        return None
    return (f"The interrupted update had moved the clone {u['clone']} from {u['from'][:12]} to {u['to'][:12]}; "
            f"the install is back at {u['from'][:12]}. To install {u['to'][:12]}, run ./install.sh in {u['clone']}, "
            "or run mifal update again.")


def rollback(h, journal: dict, fs: Fs) -> None:
    steps, pre = journal["steps"], journal["pre"]
    through = mf.linked_skill_folders(journal)
    for op in reversed(steps[pre:]):
        _undo(h, op, fs, through)
    if journal["previous"] is None:
        fs.remove(h.manifest, f"remove {h.show(h.manifest)}")
    else:
        fs.out(f"restore {h.show(h.manifest)}")
        if not fs.dry_run:
            mf.write_text(h.manifest, journal["previous"])
    if not fs.dry_run:
        _remove_txn(h)
    for op in reversed(steps[:pre]):
        _undo(h, op, fs, through)


def _undo(h, op: dict, fs: Fs, through=()) -> None:
    kind = op["op"]
    touched = [Path(op[k]) for k in ("path", "from", "to") if k in op]
    link = next((d for d in (mf.diverted(t, through) for t in touched) if d), None)
    if link:
        fs.out(f"kept {h.show(touched[0])}: {h.show(link)} is a link now, changed after the interrupted install")
        return
    if kind == "move":
        src, dst = Path(op["from"]), Path(op["to"])
        if not fs.exists(dst):
            return
        if fs.exists(src):
            fs.out(f"kept {h.show(dst)}: {h.show(src)} exists again")
        else:
            fs.move(dst, src, f"restore {h.show(src)}")
        return
    if kind == "copy":
        dst = Path(op["to"])
        if fs.exists(dst):
            fs.remove(dst)
        return
    path = Path(op["path"])
    if kind == "block":
        _undo_block(h, op, path, fs)
        return
    if kind == "rmdir":
        if not fs.exists(path):
            fs.mkdir(path, f"restore {h.show(path)}")
        return
    if kind == "mkdir":
        if fs.state(path) == ("dir",) and fs.empty(path):
            fs.remove(path, f"remove {h.show(path)}")
        return
    if not fs.exists(path):
        return
    want = ("file", op["sha256"]) if kind == "write" else ("link", op["target"])
    if fs.state(path) == want:
        fs.remove(path, f"remove {h.show(path)}")
    else:
        fs.out(f"kept {h.show(path)}: changed after the interrupted install")


def _undo_block(h, op: dict, path: Path, fs: Fs) -> None:
    copy = Path(op["copy"]) if op["copy"] else None
    now = fs.state(path)
    if now == ("file", op["sha256"]):
        if copy and fs.exists(copy):
            fs.remove(path)
            fs.move(copy, path, f"restore {h.show(path)}")
        elif op["before"] is None:
            fs.remove(path, f"remove {h.show(path)}")
        else:
            fs.out(f"kept {h.show(path)}: its saved copy is missing")
    elif now != MISSING and now != ("file", op["before"]):
        fs.out(f"kept {h.show(path)}: changed after the interrupted install")
