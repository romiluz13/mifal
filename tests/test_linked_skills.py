"""An agent's skills folder that is a link to a real folder in the person's home (fixture G2): the install writes its
links there, keeps the person's link and folder, and uninstall removes only Mifal's links."""

import unittest

from support import Sandbox, snapshot
from test_update import Update

NOTE = "~/.claude-alt/skills is a link to ~/.claude/skills; Mifal writes there"


class G2(Sandbox):
    """~/.claude-alt is Claude's root (CLAUDE_CONFIG_DIR); its skills folder links to ~/.claude/skills."""

    def setUp(self):
        super().setUp()
        self.harness_fakes("claude")
        self.target = self.home / ".claude/skills"
        self.target.mkdir(parents=True)
        (self.target / "mine").mkdir()
        (self.target / "mine/SKILL.md").write_text("my own skill\n")
        self.alt = self.home / ".claude-alt"
        self.alt.mkdir()
        self.link = self.alt / "skills"
        self.link.symlink_to("../.claude/skills")
        self.env_root = {"CLAUDE_CONFIG_DIR": str(self.alt)}

    def install(self, *args, **kw):
        return super().install("--harness", "claude", *args, **{**self.env_root, **kw})

    def mifal(self, *args, **kw):
        return super().mifal(*args, **{**self.env_root, **kw})

    def entries(self, kind):
        return [e["path"] for e in self.manifest()["entries"] if e["kind"] == kind]

    def assert_link_and_target_intact(self):
        self.assertTrue(self.link.is_symlink())
        self.assertEqual(self.link.readlink().as_posix(), "../.claude/skills")
        self.assertTrue(self.target.is_dir() and not self.target.is_symlink())
        self.assertEqual((self.target / "mine/SKILL.md").read_text(), "my own skill\n")


class OtherHome(G2):
    """The second Claude home that shares the folder gets the skills but no Guide, and the doctor says so."""

    def doctor(self):
        return Sandbox.mifal(self, "doctor", check=False)

    def test_the_doctor_names_the_other_claude_home_that_shares_the_skills_without_the_guide(self):
        self.install()
        self.assertIn("note also seen by ~/.claude: it shares ~/.claude/skills, but Mifal serves ~/.claude-alt, so "
                      "Claude Code started there gets the skills without the Guide", self.doctor().stdout)

    def test_the_doctor_says_nothing_when_no_other_home_shares_the_folder(self):
        (self.home / "shared").mkdir()
        self.link.unlink()
        self.link.symlink_to("../shared")
        self.install()
        self.assertNotIn("also seen by", self.doctor().stdout)


class Install(G2):
    def test_the_install_writes_its_links_into_the_linked_folder_and_keeps_the_link(
        self,
    ):
        result = self.install()
        self.assertIn(NOTE, result.stdout)
        self.assert_link_and_target_intact()
        self.assertEqual(
            (self.target / "tdd").readlink(), self.home.joinpath(".agents/skills/tdd")
        )
        self.assertEqual(
            (self.link / "tdd").resolve(),
            self.home.joinpath(".agents/skills/tdd").resolve(),
        )
        self.assertFalse((self.home / ".claude/CLAUDE.md").exists())
        self.assertIn(
            "@~/.agents/mifal/AGENTS.md", (self.alt / "CLAUDE.md").read_text()
        )

    def test_the_dry_run_prints_the_note_and_the_links_and_writes_nothing(self):
        before = snapshot(self.home)
        result = self.install("--dry-run")
        self.assertIn(NOTE, result.stdout)
        self.assertIn("link ~/.claude-alt/skills/tdd -> ", result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_the_linked_skills_folder_is_never_a_dir_entry_at_the_link_or_at_its_target(
        self,
    ):  # L2's invariant
        self.install()
        dirs = self.entries("dir")
        for path in (
            self.link,
            self.target,
            self.alt / "skills",
            self.target.resolve(),
        ):
            self.assertNotIn(str(path), dirs)
        links = self.entries("symlink")
        self.assertIn(str(self.link / "tdd"), links)
        self.assertNotIn(str(self.target / "tdd"), links)

    def test_the_note_also_names_the_other_root_that_shares_the_folder(self):
        self.assertIn("also seen by ~/.claude", self.install().stdout)

    def test_nothing_is_claimed_when_no_other_root_shares_the_folder(self):
        other = self.home / "shared"
        other.mkdir()
        self.link.unlink()
        self.link.symlink_to("../shared")
        self.assertNotIn("also seen by", self.install().stdout)

    def test_an_absolute_link_to_a_folder_in_the_home_is_a_linked_folder_too(self):
        self.link.unlink()
        self.link.symlink_to(self.target)
        self.install()
        self.assertEqual(self.link.readlink(), self.target)
        self.assertTrue((self.target / "tdd").is_symlink())

    def test_a_skill_of_the_same_name_behind_the_link_is_backed_up_and_restored(self):
        theirs = self.target / "tdd"
        theirs.mkdir()
        (theirs / "SKILL.md").write_text("their tdd\n")
        result = self.install("--dry-run")
        self.assertRegex(result.stdout, r"backup ~/\.claude-alt/skills/tdd -> ")
        self.install()
        self.assertTrue((self.target / "tdd").is_symlink())
        self.mifal("uninstall")
        self.assertEqual((self.target / "tdd/SKILL.md").read_text(), "their tdd\n")

    def test_installing_again_changes_nothing(self):
        self.install()
        before = snapshot(self.home)
        self.assertIn("Nothing to change", self.install().stdout)
        self.assertEqual(snapshot(self.home), before)


class Doctor(G2):
    def test_the_doctor_passes_through_the_link(self):
        self.install()
        result = self.mifal("doctor", check=False)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertRegex(
            result.stdout,
            r"(?m)^PASS skills claude: \d+ links in ~/\.claude-alt/skills",
        )
        self.assertNotIn("your skills claude", result.stdout)
        self.assertEqual(
            [l for l in result.stdout.splitlines() if l.startswith("FAIL")], []
        )


class Uninstall(G2):
    def test_uninstall_removes_only_mifals_links_and_the_link_and_its_folder_survive(
        self,
    ):
        self.install()
        self.mifal("uninstall")
        self.assert_link_and_target_intact()
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), ["mine"])
        self.assertFalse((self.alt / "CLAUDE.md").exists())

    def test_the_link_and_an_empty_target_folder_survive_uninstall(self):
        (self.target / "mine/SKILL.md").unlink()
        (self.target / "mine").rmdir()
        self.install()
        self.mifal("uninstall")
        self.assertTrue(self.link.is_symlink())
        self.assertEqual(self.link.readlink().as_posix(), "../.claude/skills")
        self.assertTrue(self.target.is_dir() and not self.target.is_symlink())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_a_dry_run_uninstall_writes_nothing(self):
        self.install()
        before = snapshot(self.home)
        self.mifal("uninstall", "--dry-run")
        self.assertEqual(snapshot(self.home), before)


class LinkedUpdate(Update):
    def install(self, *args, **kw):
        self.harness_fakes("claude")
        target = self.home / ".claude/skills"
        second = self.home / ".claude-alt"
        if not second.exists():
            target.mkdir(parents=True)
            (target / "mine").mkdir()
            (target / "mine/SKILL.md").write_text("my own skill\n")
            second.mkdir()
            (second / "skills").symlink_to("../.claude/skills")
        env = {"CLAUDE_CONFIG_DIR": str(second)}
        return super().install("--harness", "claude", *args, **{**env, **kw})

    def mifal(self, *args, **kw):
        return super().mifal(
            *args, **{"CLAUDE_CONFIG_DIR": str(self.home / ".claude-alt"), **kw}
        )

    def test_update_adds_a_new_skills_link_through_the_linked_folder(self):
        self.publish(
            "add a skill",
            **{
                "skills/newskill/SKILL.md": "---\nname: newskill\ndescription: x\n---\nBody\n"
            },
        )
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.home / ".claude/skills/newskill").is_symlink())
        self.assertTrue((self.home / ".claude-alt/skills").is_symlink())
        self.assertEqual(
            (self.home / ".claude/skills/mine/SKILL.md").read_text(), "my own skill\n"
        )
        dirs = [e["path"] for e in self.manifest()["entries"] if e["kind"] == "dir"]
        self.assertNotIn(str(self.home / ".claude-alt/skills"), dirs)
        self.assertNotIn(str(self.home / ".claude/skills"), dirs)

    def test_update_with_nothing_new_says_so_and_changes_nothing(self):
        before = snapshot(self.home)
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.home), before)


class Refusals(G2):
    """L3: a link that does not lead straight to a real folder in the home is refused, nothing is written, and
    --overwrite-edits is neither offered nor effective."""

    def make_dangling(self):
        self.link.unlink()
        self.link.symlink_to("../nowhere")
        return "../nowhere"

    def make_file(self):
        (self.home / "afile").write_text("x\n")
        self.link.unlink()
        self.link.symlink_to("../afile")
        return "../afile"

    def make_link_to_link(self):
        (self.home / "hop").symlink_to(self.target)
        self.link.unlink()
        self.link.symlink_to("../hop")
        return "../hop"

    def make_symlinked_ancestor(self):
        real = self.home / "real-parent"
        (real / "skills").mkdir(parents=True)
        (self.home / "via").symlink_to(real)
        self.link.unlink()
        self.link.symlink_to("../via/skills")
        return "../via/skills"

    def check(self, make, reason):
        raw = make()
        for flags in ((), ("--overwrite-edits",)):
            with self.subTest(reason=reason, flags=flags):
                before = snapshot(self.home)
                result = self.install(*flags, check=False)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("~/.claude-alt/skills", result.stdout)
                self.assertIn(raw, result.stdout)
                self.assertIn("Nothing was written.", result.stdout)
                self.assertNotIn("--overwrite-edits", result.stdout)
                self.assertIn("--harness", result.stdout)
                self.assertEqual(snapshot(self.home), before)
                self.assertFalse((self.home / ".agents/mifal-saved").exists())

    def test_a_dangling_link_is_refused(self):
        self.check(self.make_dangling, "dangling")

    def test_a_link_to_a_file_is_refused(self):
        self.check(self.make_file, "file")

    def test_a_link_to_another_link_is_refused(self):
        self.check(self.make_link_to_link, "link to link")

    def test_a_chain_through_a_symlinked_ancestor_is_refused(self):
        self.check(self.make_symlinked_ancestor, "symlinked ancestor")


class Outside(G2):
    def setUp(self):
        super().setUp()
        self.outside = self.root / "outside-skills"
        self.outside.mkdir()
        self.link.unlink()
        self.link.symlink_to(self.outside)

    def test_a_target_outside_the_home_is_refused_with_and_without_overwrite_edits(
        self,
    ):
        for flags in ((), ("--overwrite-edits",)):
            with self.subTest(flags=flags):
                before = snapshot(self.home)
                result = self.install(*flags, check=False)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("~/.claude-alt/skills", result.stdout)
                self.assertIn(str(self.outside), result.stdout)
                self.assertIn("--allow-root-outside-home", result.stdout)
                self.assertEqual(snapshot(self.home), before)
                self.assertEqual(list(self.outside.iterdir()), [])

    def test_the_flag_lets_the_install_write_there_and_uninstall_leaves_the_folder(
        self,
    ):
        result = self.install("--allow-root-outside-home")
        self.assertIn("Mifal writes there", result.stdout)
        self.assertTrue((self.outside / "tdd").is_symlink())
        self.mifal("uninstall")
        self.assertTrue(self.link.is_symlink())
        self.assertTrue(self.outside.is_dir())
        self.assertEqual(list(self.outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
