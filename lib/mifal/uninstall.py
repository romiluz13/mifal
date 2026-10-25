"""Reverse an install from its Manifest, keeping anything the user changed since."""
from __future__ import annotations

from pathlib import Path

from . import harness
from .herdr import removal_hint
from .install import moved_folders
from .journal import Fs
from .manifest import Home, diverted, expected, linked_skill_folders, read_rules, state, write_text


def _depth_first(entries):
    return sorted(entries, key=lambda e: (-len(Path(e["path"]).parts), e["path"]))


def uninstall(h: Home, data: dict, fs: Fs) -> int:
    moved = moved_folders(h, data.get("folders", {}))
    if moved:
        for line in moved:
            fs.out(line)
        fs.out("Nothing was removed. Put those folders back where they were, then run uninstall again.")
        return 1
    kept = []
    links = {}
    entries = []
    through = linked_skill_folders(data)
    for e in data["entries"]:
        link = diverted(e["path"], through) or (diverted(e["backup"], through) if e["kind"] == "backup" else None)
        if link:
            links.setdefault(link, h.show(e["path"]))
        else:
            entries.append(e)
    for link in sorted(links):
        kept.append(f"kept {h.show(link)}: it is a link now, so Mifal leaves it and what it leads to alone")

    for e in entries:
        if e["kind"] == "block":
            _remove_block(h, e, fs, kept)

    for e in entries:
        if e["kind"] not in ("file", "symlink"):
            continue
        path = Path(e["path"])
        now = fs.state(path)
        if now == expected(e):
            fs.remove(path, f"remove {h.show(path)}")
        elif fs.exists(path):
            kept.append(f"kept {h.show(path)}: changed since install")

    dirs = [Path(e["path"]) for e in _depth_first(entries) if e["kind"] == "dir"]
    _remove_empty(h, dirs, fs)

    for e in entries:
        if e["kind"] == "backup":
            original, saved = Path(e["path"]), Path(e["backup"])
            if not fs.exists(saved):
                kept.append(f"missing backup {h.show(saved)} for {h.show(original)}")
            elif fs.exists(original):
                kept.append(f"kept backup {h.show(saved)}: {h.show(original)} exists again")
            else:
                for parent in reversed([p for p in original.parents if not fs.exists(p)]):
                    fs.mkdir(parent, f"create {h.show(parent)}")
                fs.move(saved, original, f"restore {h.show(original)} <- {h.show(saved)}")
        elif e["kind"] == "saved" and fs.exists(Path(e["path"])):
            kept.append(f"kept {h.show(e['path'])}: your edited copy of {h.show(e['original'])}")

    fs.remove(h.manifest, f"remove {h.show(h.manifest)}")
    _remove_empty(h, dirs, fs)
    for line in kept:
        fs.out(line)
    hint = removal_hint(data.get("dependencies", {}).get("herdr"), h.show)
    if hint:
        fs.out(hint)
    return 0


def _remove_empty(h, dirs, fs):
    for path in dirs:
        if fs.state(path) == ("dir",) and fs.empty(path):
            fs.remove(path, f"remove {h.show(path)}")


def _remove_block(h, e, fs, kept):
    path = Path(e["path"])
    if not fs.exists(path):
        return
    if state(path)[0] != "file":
        kept.append(f"kept the Mifal block in {h.show(path)}: it is not a plain file now, so Mifal leaves it alone; "
                    "remove the block between the mifal:begin and mifal:end lines yourself")
        return
    text = read_rules(path)
    found = harness.BLOCK.findall(text)
    mine = [b for b in found if harness.digest(b) == e["sha256"]]
    if not mine:
        if found:
            kept.append(f"kept the Mifal block in {h.show(path)}: changed since install")
        return
    at = text.index(mine[0])
    start = at - len(e["sep"]) if e["sep"] and text[:at].endswith(e["sep"]) else at
    rest = text[:start] + text[at + len(mine[0]):]
    if rest == "" and e["created"]:
        fs.remove(path, f"remove {h.show(path)}")
    else:
        fs.out(f"remove the Mifal block from {h.show(path)}")
        if not fs.dry_run:
            write_text(path, rest)
