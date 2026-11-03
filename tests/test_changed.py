import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import PYTHON, REPO

sys.path.insert(0, str(Path(__file__).resolve().parent))
import changed_tests  # noqa: E402

ALWAYS = ("test_readme", "test_content")
SHIPPED = ("skills/team-lead/scripts", "skills/team-lead/stewardship", "tools", "tools/herdr_adapter/tests")
ODD = ("with space.md", "new\nline.txt", "-leading-dash", "tab\there", 'quote".txt', "back\\slash", "ünï.txt")
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}


class Disposable(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="mifal-changed-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        patch = mock.patch.dict(os.environ, GIT_ENV)
        patch.start()
        self.addCleanup(patch.stop)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, check=True,
                              text=True).stdout.strip()

    def write(self, rel, text="x\n"):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "--no-verify", "-m", message)
        return self.git("rev-parse", "HEAD")


class ChangeSet(Disposable):
    """Every path a builder touched since BASE counts: committed, staged, unstaged and untracked."""

    def setUp(self):
        super().setUp()
        self.repo = self.root / "repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.write("kept.txt")
        self.write("old.txt", "a file long enough to be seen as the same file after a rename\n" * 4)
        self.write("gone.txt")
        self.write("edited.txt")
        self.base = self.commit("base")

    def paths(self):
        return set(changed_tests.change_set(self.repo, self.base))

    def test_no_changes_is_empty(self):
        self.assertEqual(self.paths(), set())

    def test_each_of_the_four_sources_counts(self):
        self.write("committed.txt")
        self.commit()
        self.write("staged.txt")
        self.git("add", "staged.txt")
        self.write("edited.txt", "now different\n")
        self.write("untracked.txt")
        self.assertEqual(self.paths(), {"committed.txt", "staged.txt", "edited.txt", "untracked.txt"})

    def test_odd_file_names_come_through_whole(self):
        for i, name in enumerate(ODD):
            self.write(name)
            if i % 2:
                self.git("add", "--", name)
        self.assertEqual(self.paths(), set(ODD))

    def test_a_committed_rename_counts_both_sides(self):
        self.git("mv", "old.txt", "new.txt")
        self.commit()
        self.assertEqual(self.paths(), {"old.txt", "new.txt"})

    def test_a_staged_rename_counts_both_sides(self):
        self.git("mv", "old.txt", "new.txt")
        self.assertEqual(self.paths(), {"old.txt", "new.txt"})

    def test_deletions_count_committed_or_not(self):
        self.git("rm", "-q", "gone.txt")
        self.commit()
        (self.repo / "kept.txt").unlink()
        self.assertEqual(self.paths(), {"gone.txt", "kept.txt"})

    def test_committed_changes_are_measured_from_the_merge_base(self):
        self.git("checkout", "-q", "-b", "work")
        self.write("mine.txt")
        self.commit()
        self.git("checkout", "-q", self.base)
        self.write("theirs.txt")
        later = self.commit()
        self.git("checkout", "-q", "work")
        self.assertEqual(set(changed_tests.change_set(self.repo, later)), {"mine.txt"})

    def test_ignored_files_do_not_count(self):
        self.write(".gitignore", "*.pyc\n")
        self.commit()
        self.write("cache.pyc")
        self.assertEqual(self.paths(), {".gitignore"})


class Selection(unittest.TestCase):
    """A mapping narrows only where the tests that read a path are known; anything else runs wider."""

    def setUp(self):
        self.repo = REPO

    def select(self, *paths):
        return changed_tests.select(paths, self.repo)

    def assertNarrow(self, choice):
        self.assertEqual((choice.tests, choice.shipped), (ALWAYS, ()))

    def assertTestsOnly(self, choice):
        self.assertEqual((choice.tests, choice.shipped), (changed_tests.ALL, ()))

    def assertEverything(self, choice):
        self.assertEqual((choice.tests, choice.shipped), (changed_tests.ALL, SHIPPED))

    def test_no_changes_still_runs_the_readme_and_content_tests(self):
        self.assertNarrow(self.select())

    def test_a_docs_only_change_adds_nothing(self):
        self.assertNarrow(self.select("CHANGELOG.md", "MAINTAINING.md", "docs/adr/0001-one-installer.md"))

    def test_a_docs_only_name_inside_another_folder_is_not_docs(self):
        self.assertEverything(self.select("skills/team-lead/CHANGELOG.md"))
        self.assertEverything(self.select("docs/TRUST.md"))

    def test_a_changed_test_module_runs_all_of_tests_because_modules_import_each_other(self):
        for path in ("tests/test_content.py", "tests/support.py", "tests/helpers/readme_writes.py"):
            self.assertTestsOnly(self.select(path))

    def test_the_runner_itself_runs_everything(self):
        self.assertEverything(self.select("tests/run.sh"))

    def test_validator_and_tools_changes_reach_their_consumers(self):
        for path in ("skills/team-lead/scripts/validate_contracts.py", "tools/review-snapshot.py",
                     "tools/herdr_adapter/lead.py", "skills/tdd/SKILL.md"):
            self.assertEverything(self.select(path))

    def test_an_unknown_path_runs_everything(self):
        for path in ("lib/mifal/install.py", ".github/workflows/test.yml", "new-top-level-thing", "-leading-dash",
                     "new\nline.md"):
            self.assertEverything(self.select(path))

    def test_the_widest_path_wins(self):
        self.assertEverything(self.select("CHANGELOG.md", "tests/test_content.py", "lib/mifal/cli.py"))
        self.assertTestsOnly(self.select("CHANGELOG.md", "tests/test_content.py"))

    def test_a_deleted_selected_test_widens_rather_than_finding_nothing(self):
        self.repo = Path(tempfile.mkdtemp(prefix="mifal-changed-")).resolve()
        self.addCleanup(shutil.rmtree, self.repo, True)
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_readme.py").write_text("")
        self.assertEverything(self.select("CHANGELOG.md"))
        self.assertEverything(self.select())

    def test_the_shipped_suites_are_the_ones_the_full_run_runs(self):
        loops = re.findall(r"for dir in ([^;]+); do", (REPO / "tests" / "run.sh").read_text())
        self.assertEqual([tuple(loop.split()) for loop in loops if "$" not in loop], [SHIPPED])
        self.assertEqual(changed_tests.SHIPPED, SHIPPED)

    def test_every_path_gets_a_reason(self):
        choice = self.select("CHANGELOG.md", "tests/test_content.py", "lib/mifal/cli.py")
        said = "\n".join(choice.reasons)
        for path in ("CHANGELOG.md", "tests/test_content.py", "lib/mifal/cli.py"):
            self.assertIn(path, said)



class DocsConsumers(unittest.TestCase):
    """A docs-only path may narrow the run only while no code outside test_readme and test_content reads it."""

    READERS = {"tests/test_readme.py", "tests/test_content.py", "tests/helpers/readme_writes.py",
               "tests/changed_tests.py", "tests/test_changed.py"}
    # Code that names a docs file without reading what it says.
    NAMES_ONLY = {("README.md", "tests/test_update.py"): "copies a disposable clone's README into a commit",
                  ("MAINTAINING.md", "maint/upstream.py"): "prints the file's name",
                  ("MAINTAINING.md", ".github/workflows/upstream.yml"): "prints the file's name",
                  ("docs/INSTALL.md", "tests/test_homes.py"): "a docstring"}

    def code(self):
        files = subprocess.run(["git", "-C", str(REPO), "ls-files", "--cached", "--others", "--exclude-standard",
                                "-z"], capture_output=True, check=True).stdout.decode().split("\0")
        return [p for p in files if p and (p.endswith((".py", ".sh", ".yml")) or p.startswith("bin/"))
                and (REPO / p).is_file()]

    def docs(self):
        files = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--", *changed_tests.DOCS,
                                *changed_tests.DOCS_FOLDERS], capture_output=True, check=True).stdout.decode()
        return [p for p in files.split("\0") if p]

    def test_no_other_code_reads_a_docs_only_file(self):
        docs = self.docs()
        self.assertIn("CHANGELOG.md", docs)
        self.assertIn("docs/adr/0001-one-installer.md", docs)
        code = {p: (REPO / p).read_text(encoding="utf-8", errors="replace") for p in self.code()}
        found = []
        for doc in docs:
            name = "/".join(Path(doc).parts[-2:])
            for path, text in code.items():
                if path not in self.READERS and name in text and (name, path) not in self.NAMES_ONLY:
                    found.append(f"{path} names {doc}")
        self.assertEqual(found, [], "a docs-only file has a new reader: map it in tests/changed_tests.py, "
                                    "or show the reader ignores its content")



class RunChanged(Disposable):
    """tests/run.sh --changed BASE in a disposable project whose tests log what ran."""

    TEST = ("import unittest\n\n\nclass T(unittest.TestCase):\n    def test_it(self):\n"
            "        with open({log!r}, 'a') as f:\n            f.write({name!r} + '\\n')\n        self.assertTrue({ok})\n")

    def setUp(self):
        super().setUp()
        self.repo = self.root / "repo"
        self.log = self.root / "ran.log"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "tests").mkdir()
        for name in ("run.sh", "changed_tests.py"):
            shutil.copy2(REPO / "tests" / name, self.repo / "tests" / name)
        for name in ("tests/test_readme.py", "tests/test_content.py", "tests/test_other.py",
                     *(root + "/test_" + root.replace("/", "_").replace("-", "_") + ".py" for root in SHIPPED)):
            self.fake_test(name)
        self.write("CHANGELOG.md")
        self.write("lib/code.py")
        self.base = self.commit("base")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        os.symlink(PYTHON, self.bin / "python3")

    def fake_test(self, rel, ok=True):
        self.write(rel, self.TEST.format(log=str(self.log), name=rel, ok=ok))

    def run_sh(self, *args, script=None):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.root), "LANG": "en_US.UTF-8", **GIT_ENV}
        return subprocess.run(["/bin/bash", str(script or self.repo / "tests" / "run.sh"), *args],
                              capture_output=True, text=True, env=env, timeout=300)

    def ran(self):
        return sorted(self.log.read_text().splitlines()) if self.log.exists() else []

    def interpreters_recorded(self, *args):
        """Run a copy of run.sh whose two interpreters only record that they started."""
        calls = self.root / "calls.log"
        fake = self.root / "fakepy"
        fake.write_text(f'#!/bin/bash\necho "$0 $*" >> "{calls}"\nexit 1\n')
        fake.chmod(0o755)
        (self.bin / "python3").unlink()
        os.symlink(fake, self.bin / "python3")
        script = (self.repo / "tests" / "run.sh").read_text()
        self.assertIn("/usr/bin/python3", script)
        copy = self.repo / "tests" / "recorded.sh"
        copy.write_text(script.replace("/usr/bin/python3", str(fake)))
        result = self.run_sh(*args, script=copy)
        return result, calls.read_text() if calls.exists() else ""

    def test_a_bad_base_stops_before_any_interpreter_starts(self):
        tree = self.git("rev-parse", "HEAD:tests")
        unrelated = subprocess.run(["git", "-C", str(self.repo), "commit-tree", tree, "-m", "orphan"],
                                   capture_output=True, text=True, check=True).stdout.strip()
        for base in ("no-such-ref", "", "--output=x", "-q", "HEAD:tests", tree, unrelated):
            with self.subTest(base=base):
                result, calls = self.interpreters_recorded("--changed", base)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("--changed", result.stderr)
                self.assertEqual(calls, "")
                self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.repo / "x").exists())

    def test_conflicting_arguments_stop_before_any_interpreter_starts(self):
        for args in (["--changed"], ["--changed", "HEAD", "-q"], ["-q", "--changed", "HEAD"], ["--changed=HEAD"],
                     ["--changed", "HEAD", "--changed", "HEAD"]):
            with self.subTest(args=args):
                result, calls = self.interpreters_recorded(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("usage: tests/run.sh --changed BASE", result.stderr)
                self.assertEqual(calls, "")

    def test_a_docs_only_change_runs_the_readme_and_content_tests_under_both_pythons(self):
        self.write("CHANGELOG.md", "edited\n")
        result = self.run_sh("--changed", self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ran(), ["tests/test_content.py"] * 2 + ["tests/test_readme.py"] * 2)
        self.assertIn("not release evidence", result.stderr)

    def test_an_unmapped_change_runs_everything_under_both_pythons(self):
        self.write("lib/code.py", "edited\n")
        self.commit()
        result = self.run_sh("--changed", self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        everything = [line for line in self.ran()]
        self.assertEqual(len(everything), 2 * 7)
        self.assertEqual(len(set(everything)), 7)

    def test_failures_are_counted_and_the_other_suites_still_run(self):
        self.fake_test("tools/test_tools.py", ok=False)
        result = self.run_sh("--changed", self.base)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.ran().count("tools/herdr_adapter/tests/test_tools_herdr_adapter_tests.py"), 2)
        self.assertEqual(self.ran().count("tools/test_tools.py"), 2)

    def test_a_missing_always_run_test_widens_the_run(self):
        (self.repo / "tests" / "test_content.py").unlink()
        self.commit()
        base = self.git("rev-parse", "HEAD")
        self.write("CHANGELOG.md", "edited\n")
        result = self.run_sh("--changed", base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tests/test_other.py", self.ran())
        self.assertIn("tools/test_tools.py", self.ran())

    def test_without_changed_the_runner_behaves_as_before(self):
        result = self.run_sh()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.ran()), 2 * 7)
        self.assertNotIn("not release evidence", result.stderr)
        self.log.unlink()
        result = self.run_sh("-q")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(set(self.ran())), ["tests/test_content.py", "tests/test_other.py",
                                                   "tests/test_readme.py"])
        self.assertIn("the shipped suites did not run", result.stderr)


if __name__ == "__main__":
    unittest.main()
