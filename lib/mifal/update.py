"""mifal update: fetch in the recorded clone, preview the incoming revision, then install exactly that tree."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from . import harness
from . import install as inst
from . import journal

REPO_URL = "https://github.com/romiluz13/mifal.git"


RELEASE_TAG = re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)$", re.ASCII)
TAGS = "refs/mifal/tags"


class Refused(Exception):
    pass


class Current(Exception):
    """The install already contains the newest release; there is nothing to install."""


def _git(clone, *args, check=True):
    result = subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True,
                            stdin=subprocess.DEVNULL)
    if check and result.returncode != 0:
        raise Refused(f"git {' '.join(args)} failed in {clone}: {result.stderr.strip()}")
    return result


def manual_commands(source: dict) -> list:
    url = source.get("url") or REPO_URL
    return [f"git clone {url} mifal", "cd mifal && ./install.sh"]


def latest_release(clone, upstream):
    """(tag, commit) of the highest vX.Y.Z release, or None. Only tags fetched into Mifal's own namespace count, and
    only those on the recorded upstream branch whose VERSION is the tag, so a mistyped, off-branch, local or
    foreign tag cannot become the release."""
    found = []
    for name in _git(clone, "for-each-ref", "--format=%(refname:strip=3)", TAGS).stdout.split():
        m = RELEASE_TAG.match(name)
        sha = _git(clone, "rev-parse", "--verify", "--quiet", f"{TAGS}/{name}^{{commit}}", check=False).stdout.strip()
        if not m or not sha:
            continue
        if _git(clone, "merge-base", "--is-ancestor", sha, upstream, check=False).returncode != 0:
            continue
        if _git(clone, "show", f"{sha}:VERSION", check=False).stdout.strip() != name[1:]:
            continue
        found.append((tuple(map(int, m.groups())), name, sha))
    return max(found)[1:] if found else None


def candidate(source: dict, branch: bool = False) -> tuple:
    """(clone, label, candidate sha, clone HEAD) after fetching; refuses before any write.

    The candidate is the newest release tag, so a commit that is on the branch but not yet released is never offered.
    A clone whose remote has no valid release tag, or an update run with --branch, follows its recorded upstream branch."""
    clone = Path(source["path"])
    upstream = source.get("upstream")
    if not upstream:
        raise Refused(f"{clone} has no upstream branch recorded; set one with "
                      f"`git -C {clone} branch --set-upstream-to=origin/main` and run ./install.sh there.")
    if _git(clone, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise Refused(f"{clone} has uncommitted changes to tracked files; commit or stash them first.")
    remote = upstream.split("/", 1)[0]
    _git(clone, "fetch", "--quiet", remote)
    _git(clone, "fetch", "--quiet", "--no-tags", "--prune", remote, f"+refs/tags/v*:{TAGS}/v*")
    head = _git(clone, "rev-parse", "HEAD").stdout.strip()
    release = None if branch else latest_release(clone, upstream)
    if release:
        label, sha = f"release {release[0]}", release[1]
        installed = source.get("revision")
        if installed and installed != sha and _git(clone, "merge-base", "--is-ancestor", sha, installed,
                                                   check=False).returncode == 0:
            raise Current(label)
    else:
        label, sha = upstream, _git(clone, "rev-parse", upstream).stdout.strip()
    is_ancestor = lambda old, new: _git(clone, "merge-base", "--is-ancestor", old, new, check=False).returncode == 0
    if not (release and is_ancestor(sha, head)) and not is_ancestor(head, sha):
        raise Refused(f"{label} ({sha[:12]}) is not a fast-forward of the clone's HEAD ({head[:12]}): "
                      "the clone has its own commits or upstream rewrote history. Nothing was changed.")
    return clone, label, sha, head


def export(clone: Path, sha: str, into: Path) -> None:
    """The tree of exactly sha, written to into."""
    archive = into / "tree.tar"
    with open(archive, "wb") as f:
        subprocess.run(["git", "-C", str(clone), "archive", "--format=tar", sha], stdout=f, check=True,
                       stdin=subprocess.DEVNULL)
    tree = into / "tree"
    tree.mkdir()
    tree = tree.resolve()
    with tarfile.open(archive) as t:
        for member in t.getmembers():
            target = os.path.realpath(tree / member.name)
            if not target.startswith(str(tree) + os.sep):
                raise Refused(f"the archive of {sha} has an entry outside its tree: {member.name}")
        t.extractall(tree, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
    archive.unlink()


def _plan(h, tree, version, args, data, src):
    """The plan for installing tree into the recorded homes. Agents that were skipped stay recorded as skipped."""
    records = data.get("harnesses") or {}
    env, notes = harness.recorded_env(data, os.environ, h.show)
    notes += harness.unserved(h.home, data, os.environ, h.show)
    wired = [n for n, r in records.items() if r["status"] == "wired"]
    plan = inst.make_plan(h, tree, version, args.overwrite_edits, wired if records else None, env, source_record=src)
    for name, rec in records.items():
        plan.data["harnesses"].setdefault(name, rec)
    return plan, notes


def update(h, data, args, out) -> int:
    source = data.get("source") or {}
    clone = Path(source["path"]) if source.get("path") else None
    if clone is None or not (clone / ".git").exists():
        out("mifal: the clone this install came from is gone. To update, clone Mifal again and install:")
        for line in manual_commands(source):
            out(f"  {line}")
        return 1
    try:
        clone, upstream, sha, head = candidate(source, getattr(args, "branch", False))
    except Current as e:
        out(f"Mifal is up to date: the installed revision already includes {e}.")
        return 0
    except Refused as e:
        out(f"mifal: {e}")
        return 1
    installed = source.get("revision")
    missing = []
    if sha == installed:
        try:
            missing = inst.engine_missing(h, data)
        except inst.Unreadable:
            pass
        if not missing:
            out(f"Mifal is up to date at {sha[:12]} ({upstream}).")
            return 0
    with tempfile.TemporaryDirectory(prefix="mifal-update-") as temp:
        export(clone, sha, Path(temp))
        tree = Path(temp) / "tree"
        version = (tree / "VERSION").read_text(encoding="utf-8").strip()
        src = dict(source, revision=sha)
        plan, notes = _plan(h, tree, version, args, data, src)
        known = installed and _git(clone, "cat-file", "-e", installed + "^{commit}", check=False).returncode == 0
        if missing:
            out(f"Mifal {version} at {sha[:12]}: this install is missing {len(missing)} file(s) this version installs:")
        else:
            log = _git(clone, "log", "--oneline", f"{installed}..{sha}" if known else sha, "-n", "50").stdout
            out(f"Update {installed[:12] if installed else 'unknown'} -> {sha[:12]} ({upstream}), Mifal {version}:")
            for line in log.splitlines():
                out(f"  {line}")
        for line in notes:
            out(line)
        if plan.conflicts or plan.stops:
            for line in plan.stops + plan.conflicts:
                out(line)
            hard = {line for line, *_ in plan.unwritable}
            if plan.unwritable:
                for line in inst.unwritable_advice(plan, False):
                    out(line)
            if any(line not in hard for line in plan.conflicts):
                out("Nothing was changed. Restore those paths, or run mifal update --overwrite-edits to save a copy of each first.")
            else:
                out("Nothing was changed.")
            return 1
        lines = list(plan.lines())
        for line in lines:
            out(line)
        if not args.yes:
            if not sys.stdin.isatty():
                out("Not applied. Run `mifal update --yes` to apply it without a prompt.")
                return 1
            if input(f"Apply {len(lines)} change(s)? [y/N] ").strip().lower() not in ("y", "yes"):
                out("Not applied.")
                return 1
            plan, _ = _plan(h, tree, version, args, data, src)
            if plan.conflicts or plan.stops or list(plan.lines()) != lines:
                for line in plan.stops + plan.conflicts:
                    out(line)
                out("Your files changed while the update waited for approval, so nothing was changed. "
                    "Run mifal update again to see the new preview.")
                return 1

        def fast_forward():
            _git(clone, "merge", "--quiet", "--ff-only", sha)

        try:
            journal.run(plan, out, last=fast_forward, update={"clone": str(clone), "from": head, "to": sha})
        except Exception as e:
            out(f"mifal: update failed ({e}); rolled back. The clone is at "
                f"{_git(clone, 'rev-parse', 'HEAD').stdout.strip()[:12]}.")
            return 1
    out(f"Updated Mifal to {version} at {sha[:12]}.")
    return 0
