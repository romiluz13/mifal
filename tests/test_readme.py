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
FAMILIES = ("Claude Code", "Codex", "Droid", "Pi", "OpenCode")
SH = re.compile(r"(?ms)^```sh\n(.*?)^```")
URL = re.compile(r"git clone (\S+)")


def text(path=README):
    return path.read_text(encoding="utf-8")


# The recorded live check behind the Support section's limits: one Mac, one date, kept by the maintainer. Pinning it makes
# an upgrade a deliberate, reviewed change to that claim and the README together; it is not evidence anything was observed.
RECORDED_CHECK = "one Mac on 2026-10-25"


def support_section(readme):
    return re.search(r"(?ms)^## Support\n(.*?)^## ", readme).group(1)


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

    def test_the_support_section_is_agent_agnostic_and_names_every_family(self):
        section = support_section(text())
        self.assertIn("agent-agnostic", section)
        for family in FAMILIES:  # every family Mifal wires, not a per-agent results table
            with self.subTest(family=family):
                self.assertIn(family, section)
        self.assertNotIn("| macOS", section)
        self.assertIn(RECORDED_CHECK, section)
        self.assertIn("kept by the maintainer, not in this repository", section)

    def test_the_support_section_states_its_limits(self):
        section = support_section(text())
        for phrase in ("entry gate", "edited before asking", "not a measure of reliability",
                       "experimental", "fake agents", "invisible to `mifal doctor`", "`disabledSkills`",
                       "`[[skills.config]]`", "`permission.skill`", "no sandbox or isolation",
                       "not live-checked", "never edits or runs a hook"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, section)

    def test_the_support_section_keeps_the_recorded_rows_and_levels(self):
        # The recorded check's per-version, per-model rows and levels, restored after the
        # table-to-prose rewrite: an upgrade drops these only by editing this pin on purpose.
        section = support_section(text())
        for row in ("Claude Code 2.1.310 with Sonnet 5.5 and with Opus 5.5",
                    "Codex 0.164.0 with GPT-6.1-Sol",
                    "Droid 0.249.0 with GLM 5.3",
                    "Pi 1.4.0 with Claude Sonnet 5 via GitHub Copilot",
                    "OpenCode 1.19.4 with GLM-5.3-Flash Free and DeepSeek V4.1 Flash Free"):
            with self.subTest(row=row):
                self.assertIn(row, section)
        for level in ("**L1**", "**L2**", "**L3**", "**L4**"):
            with self.subTest(level=level):
                self.assertIn(level, section)
        self.assertIn("except the Claude Code 2.1.310, Opus 5.5 row, which was not run", section)
        self.assertIn("L1 was partial on every row", section)
        self.assertIn("failed on Pi and OpenCode", section)

    def test_the_readme_says_herdr_stays_and_how_to_remove_it(self):
        self.assertRegex(text(INSTALL), r"Herdr stays installed")
        self.assertIn("brew uninstall herdr", text(INSTALL))


if __name__ == "__main__":
    unittest.main()
