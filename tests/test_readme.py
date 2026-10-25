import re
import subprocess
import sys
import unittest
from pathlib import Path

from support import REPO, Sandbox, changed, snapshot
from test_content import denied
from test_lifecycle import planned_paths

sys.path.insert(0, str(Path(__file__).resolve().parent / "helpers"))
import readme_writes  # noqa: E402

README = REPO / "README.md"
INSTALL = REPO / "docs" / "INSTALL.md"
TRUST = REPO / "docs" / "TRUST.md"
HARNESSES = ("claude", "codex", "droid", "pi", "opencode")
SH = re.compile(r"(?ms)^```sh\n(.*?)^```")
URL = re.compile(r"git clone (\S+)")


def text(path=README):
    return path.read_text(encoding="utf-8")


# The reviewed level of each support-matrix cell, from the recorded live check (L1, L2, L3, L4). Pinning it makes an
# upgrade a deliberate, reviewed change to this table and the README together; it is not evidence that anything was
# observed.
LEVELS = {"pass", "partial", "fail", "not run"}
PINNED_ROWS = {
    "Claude Code 2.1.310, Sonnet 5.5": ("partial", "partial", "pass", "pass"),
    "Claude Code 2.1.310, Opus 5.5": ("pass", "partial", "pass", "not run"),
    "Codex 0.164.0, GPT-6.1-Sol (`codex-work` home)": ("partial", "partial", "pass", "pass"),
    "Droid 0.249.0, GLM 5.3": ("partial", "partial", "pass", "pass"),
    "Pi 1.4.0, Claude Sonnet 5 via GitHub Copilot (`pi -ne`)": ("partial", "fail", "pass", "pass"),
    "OpenCode 1.19.4, GLM-5.3-Flash Free and DeepSeek V4.1 Flash Free": ("partial", "fail", "pass", "pass"),
}


def support_section(readme):
    return re.search(r"(?ms)^## Support\n(.*?)^## ", readme).group(1)


def matrix_rows(readme):
    """The support matrix as {agent version and model: (L1, L2, L3, L4)}."""
    split = lambda line: [c.strip() for c in line.strip().strip("|").split("|")]
    lines = [l for l in support_section(readme).splitlines() if l.startswith("| ")]
    header, rows = split(lines[0]), [split(l) for l in lines[1:]]
    assert header[0].startswith("macOS agent") and len(header) == 5, header
    return {row[0]: tuple(row[1:]) for row in rows}


class Readme(Sandbox):
    def generated_table(self):
        self.harness_fakes(*HARNESSES)
        before = snapshot(self.home)
        preview = self.install("--dry-run")
        self.install()
        planned = planned_paths(preview.stdout)
        self.assertEqual(planned, changed(before, snapshot(self.home)))
        return readme_writes.table(self.home, planned)

    def test_the_writes_table_matches_a_dry_run_with_all_five_harnesses(self):
        self.assertEqual(readme_writes.section(text(INSTALL)), self.generated_table(),
                         "regenerate it with: python3 tests/helpers/readme_writes.py")

    def test_every_command_runs_as_written_in_a_disposable_home(self):
        blocks = SH.findall(text()) + SH.findall(text(INSTALL))
        self.assertTrue(SH.findall(text()))
        self.assertIn("mifal uninstall", "".join(SH.findall(text(INSTALL))))
        url = URL.search(text()).group(1)
        origin = self.root / "origin.git"
        env = dict(self.env(), GIT_CONFIG_NOSYSTEM="1")
        git = ["git", "-C", str(self.clone), "-c", "user.name=t", "-c", "user.email=t@example.com"]
        for args in (["git", "init", "-q", "-b", "main", str(self.clone)], git + ["add", "-A"],
                     git + ["commit", "-q", "-m", "release"],
                     ["git", "clone", "-q", "--bare", str(self.clone), str(origin)]):
            subprocess.run(args, check=True, env=env, capture_output=True)
        (self.home / ".gitconfig").write_text(f'[url "{origin}"]\n\tinsteadOf = {url}\n')
        self.fake("brew", "")
        script = "set -eu\n" + "\n".join(blocks)
        result = self.run_cmd("/bin/bash", "-c", script, check=False,
                              PATH=f"{self.home}/.local/bin:{self.fakebin}:/usr/bin:/bin")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("doctor: ", result.stdout)
        self.assertNotRegex(result.stdout, r"(?m)^FAIL")

    def test_nothing_personal_in_the_readme_or_its_docs(self):
        for path in (README, INSTALL, TRUST):
            rel = str(path.relative_to(REPO))
            self.assertEqual([line for line in text(path).splitlines() if denied(rel, line)], [], rel)

    def test_the_readme_links_what_is_checked_by_a_program_and_what_relies_on_the_agent(self):
        self.assertRegex(text(TRUST), r"(?m)^## What is checked, and what relies on the agent")
        self.assertIn("(docs/TRUST.md)", text())
        self.assertIn("(docs/INSTALL.md)", text())

    def test_the_support_matrix_pins_the_recorded_cells(self):
        readme = text()
        rows = matrix_rows(readme)
        self.assertEqual(rows, PINNED_ROWS)
        for label, levels in rows.items():
            self.assertRegex(label, r"\d+\.\d+", label)
            self.assertLessEqual(set(levels), LEVELS, label)
        self.assertIn("provisional", support_section(readme))

    def test_the_pin_refuses_a_cell_upgraded_in_the_readme_alone(self):
        readme = text()
        for old in ("| fail |", "| partial |", "| not run |"):
            with self.subTest(old=old):
                self.assertIn(old, readme)
                self.assertNotEqual(matrix_rows(readme.replace(old, "| pass |", 1)), PINNED_ROWS)

    def test_the_support_section_states_its_limits(self):
        section = support_section(text())
        for phrase in ("L2 is a limitation", "entry gate", "one lead, one worker, one small task",
                       "experimental", "fake agents", "invisible to `mifal doctor`", "`disabledSkills`",
                       "`[[skills.config]]`", "`permission.skill`", "no sandbox or isolation"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, section)

    def test_the_readme_says_herdr_stays_and_how_to_remove_it(self):
        self.assertRegex(text(INSTALL), r"Herdr stays installed")
        self.assertIn("brew uninstall herdr", text(INSTALL))


if __name__ == "__main__":
    unittest.main()
