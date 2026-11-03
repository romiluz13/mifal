"""Which tests a change needs, for tests/run.sh --changed BASE.

The change set is every path that differs from BASE...HEAD, in the index, in the working tree, or untracked:
both sides of a rename and every deletion. Selection is sound or wide. test_readme and test_content always run;
a docs-only path adds nothing; any file under tests/ runs all of tests/, because test modules import each other;
shipped code runs all of tests/ and all four shipped suites, which read each other's code and the Pool; any
other path runs everything. A deleted file under tests/, a docs path that is a symlink or that a symlink Git records
reaches, and a repository with submodules, whose insides Git can't fully show, also run everything.

    python3 tests/changed_tests.py REPO COMMIT    prints the plan for tests/run.sh, one line per suite
"""
import os
import posixpath
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

ALL = "all"
ALWAYS = ("test_readme", "test_content")
SHIPPED = ("skills/team-lead/scripts", "skills/team-lead/stewardship", "tools", "tools/herdr_adapter/tests")
# Read only by test_readme and test_content; test_changed.DocsConsumers fails when another file starts reading one.
DOCS = ("CHANGELOG.md", "CONTRIBUTING.md", "GLOSSARY.md", "MAINTAINING.md", "README.md", "SECURITY.md",
        "docs/INSTALL.md")
DOCS_FOLDERS = ("docs/adr/", "docs/assets/", "docs/team-lead/")
Choice = namedtuple("Choice", "tests shipped reasons")
Group = namedtuple("Group", "name tests shipped runs")
DOCS_ONLY = Group("docs only", ALWAYS, (), "test_readme and test_content")
TESTS = Group("under tests/", ALL, (), "all of tests/, since test modules import each other")
SHIPPED_CODE = Group("shipped code", ALL, SHIPPED, "all of tests/ and all four shipped suites, which read it")
NOT_PLAIN = Group("docs reached through a symlink", ALL, SHIPPED, "everything, since a reader can name them by "
                  "another path")
DELETED_TEST = Group("deleted under tests/", ALL, SHIPPED, "everything, since a deleted test can't be selected")
UNKNOWN = Group("not mapped", ALL, SHIPPED, "everything")
ORDER = (DOCS_ONLY, TESTS, SHIPPED_CODE, NOT_PLAIN, DELETED_TEST, UNKNOWN)


def change_set(repo, base):
    """Paths changed since the merge base of base and HEAD, staged, unstaged or untracked, sorted."""
    def paths(*args):
        out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout
        return {p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p}
    diff = ("diff", "--name-only", "--no-renames", "--ignore-submodules=none", "-z")
    return sorted(paths(*diff, base + "...HEAD") | paths(*diff, "--cached") | paths(*diff)
                  | paths("ls-files", "--others", "--exclude-standard", "-z"))


def recorded(repo, base):
    """{path: {(mode, object)}} for every entry Git records at the merge base, at HEAD or in the index."""
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout
    entries = {}
    merge_base = git("merge-base", base, "HEAD").decode().strip()
    for rev in (merge_base, "HEAD", None):
        out = git("ls-tree", "-r", "--full-tree", "-z", rev) if rev else git("ls-files", "--stage", "-z")
        for line in filter(None, out.split(b"\0")):
            meta, path = line.split(b"\t", 1)
            mode, a, b = meta.decode().split(" ")
            entries.setdefault(path.decode("utf-8", "surrogateescape"), set()).add((mode, b if rev else a))
    return entries


def symlinks(repo, entries):
    """{link: {repository paths it resolves to}}, through chains; "" leaves the repository and reaches all."""
    links = {}
    for path, kinds in entries.items():
        for mode, obj in kinds:
            if mode == "120000":
                target = subprocess.run(["git", "-C", str(repo), "cat-file", "blob", obj], capture_output=True,
                                        check=True).stdout.decode("utf-8", "surrogateescape")
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
                links.setdefault(path, set()).add("" if target.startswith("/") or resolved.startswith("..")
                                                  else resolved)
    for _ in range(40):
        changed = False
        for link, ends in links.items():
            for end in list(ends):
                for other, others in links.items():
                    if other != link and (end == other or end.startswith(other + "/")):
                        for o in others:
                            new = posixpath.normpath(o + end[len(other):]) if o else ""
                            if new not in ends:
                                ends.add(new)
                                changed = True
        if not changed:
            break
    return links


def reaching(repo, path, links):
    """The symlinks through which a reader can reach path, path itself included when it is one."""
    found = [path] if path in links or os.path.islink(os.path.join(str(repo), path)) else []
    return found + sorted(link for link, ends in links.items() if link != path and any(
        end == "" or path == end or path.startswith(end + "/") for end in ends))


def group(path, repo, links):
    if path in DOCS or path.startswith(DOCS_FOLDERS):
        return NOT_PLAIN if reaching(repo, path, links) else DOCS_ONLY
    if path.startswith("tests/") and path != "tests/run.sh":
        return TESTS if os.path.lexists(os.path.join(str(repo), path)) else DELETED_TEST
    if path.startswith(("skills/", "tools/")):
        return SHIPPED_CODE
    return UNKNOWN


def shown(path):
    return path if path.isprintable() else ascii(path)


def select(paths, repo, base="HEAD"):
    """Choice(tests, shipped, reasons): tests is ALL or the tests/ modules to name, shipped the shipped suites."""
    entries = recorded(repo, base)
    links = symlinks(repo, entries)
    found = {}
    for path in paths:
        found.setdefault(group(path, repo, links), []).append(path)
    reasons = []
    for kind in ORDER:
        if kind in found:
            names = found[kind]
            listed = ", ".join(shown(p) for p in names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
            reasons.append(f"{len(names)} {kind.name} ({listed}): {kind.runs}")
    widest = ORDER[max((ORDER.index(kind) for kind in found), default=0)]
    tests, shipped = widest.tests, widest.shipped
    for path in found.get(NOT_PLAIN, []):
        reasons.append(f"{shown(path)} is reached through {', '.join(shown(p) for p in reaching(repo, path, links))}")
    missing = [m for m in ALWAYS if not (Path(repo) / "tests" / (m + ".py")).is_file()]
    if missing:
        tests, shipped = ALL, SHIPPED
        reasons.append(f"tests/{missing[0]}.py, which always runs, is missing: everything")
    gitlinks = sorted(p for p, kinds in entries.items() if any(mode == "160000" for mode, _ in kinds))
    if gitlinks or ".gitmodules" in entries or os.path.lexists(os.path.join(str(repo), ".gitmodules")):
        tests, shipped = ALL, SHIPPED
        reasons.append(f"the repository has submodules ({', '.join(map(shown, gitlinks)) or '.gitmodules'}), "
                       "and Git can't fully show a change inside one: everything")
    return Choice(tests, shipped, reasons)


def main(argv):
    repo, base = argv
    paths = change_set(repo, base)
    choice = select(paths, repo, base)
    print(f"tests/run.sh --changed: {len(paths)} path{'' if len(paths) == 1 else 's'} changed since {base[:12]} "
          "(committed, staged, unstaged and untracked)", file=sys.stderr)
    for line in choice.reasons:
        print("  " + line, file=sys.stderr)
    print("tests " + (ALL if choice.tests == ALL else " ".join(choice.tests)))
    for root in choice.shipped:
        print("shipped " + root)


if __name__ == "__main__":
    main(sys.argv[1:])
