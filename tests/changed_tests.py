"""Which tests a change needs, for tests/run.sh --changed BASE.

The change set is every path that differs from BASE...HEAD, in the index, in the working tree, or untracked:
both sides of a rename and every deletion. Selection is sound or wide. test_readme and test_content always run;
a docs-only path adds nothing; any file under tests/ runs all of tests/, because test modules import each other;
shipped code runs all of tests/ and all four shipped suites, which read each other's code and the Pool; any
other path runs everything.

    python3 tests/changed_tests.py REPO COMMIT    prints the plan for tests/run.sh, one line per suite
"""
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
UNKNOWN = Group("not mapped", ALL, SHIPPED, "everything")


def change_set(repo, base):
    """Paths changed since the merge base of base and HEAD, staged, unstaged or untracked, sorted."""
    def paths(*args):
        out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout
        return {p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p}
    diff = ("diff", "--name-only", "--no-renames", "-z")
    return sorted(paths(*diff, base + "...HEAD") | paths(*diff, "--cached") | paths(*diff)
                  | paths("ls-files", "--others", "--exclude-standard", "-z"))


def group(path):
    if path in DOCS or path.startswith(DOCS_FOLDERS):
        return DOCS_ONLY
    if path.startswith("tests/") and path != "tests/run.sh":
        return TESTS
    if path.startswith(("skills/", "tools/")):
        return SHIPPED_CODE
    return UNKNOWN


def shown(path):
    return path if path.isprintable() else ascii(path)


def select(paths, repo):
    """Choice(tests, shipped, reasons): tests is ALL or the tests/ modules to name, shipped the shipped suites."""
    order = (DOCS_ONLY, TESTS, SHIPPED_CODE, UNKNOWN)
    found = {}
    for path in paths:
        found.setdefault(group(path), []).append(path)
    reasons = []
    for kind in order:
        if kind in found:
            names = found[kind]
            listed = ", ".join(shown(p) for p in names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
            reasons.append(f"{len(names)} {kind.name} ({listed}): {kind.runs}")
    widest = order[max((order.index(kind) for kind in found), default=0)]
    tests, shipped = widest.tests, widest.shipped
    missing = [m for m in ALWAYS if not (Path(repo) / "tests" / (m + ".py")).is_file()]
    if tests != ALL and missing:
        tests, shipped = ALL, SHIPPED
        reasons.append(f"tests/{missing[0]}.py, which always runs, is missing: everything")
    return Choice(tests, shipped, reasons)


def main(argv):
    repo, base = argv
    paths = change_set(repo, base)
    choice = select(paths, repo)
    print(f"tests/run.sh --changed: {len(paths)} path{'' if len(paths) == 1 else 's'} changed since {base[:12]} "
          "(committed, staged, unstaged and untracked)", file=sys.stderr)
    for line in choice.reasons:
        print("  " + line, file=sys.stderr)
    print("tests " + (ALL if choice.tests == ALL else " ".join(choice.tests)))
    for root in choice.shipped:
        print("shipped " + root)


if __name__ == "__main__":
    main(sys.argv[1:])
