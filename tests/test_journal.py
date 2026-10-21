import unittest

from support import Sandbox, changed, snapshot

POINTS = ("after-backup", "after-write", "before-publication")


class InjectedFailure(Sandbox):
    def fail_at(self, point):
        result = self.install(check=False, MIFAL_TEST_FAIL_AT=point)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"injected failure at {point}", result.stdout + result.stderr)

    def test_a_failed_first_install_leaves_the_home_as_it_was(self):
        self.their_grilling()
        before = snapshot(self.home)
        for point in POINTS:
            with self.subTest(point=point):
                self.fail_at(point)
                self.assertEqual(snapshot(self.home), before)

    def test_a_failed_upgrade_leaves_the_installed_version(self):
        self.their_grilling()
        self.release("0.1.1", **{"old.md": "only in 0.1.1\n"})
        self.install()
        installed = snapshot(self.home)
        self.release("0.2.0", **{"old.md": None, "SKILL.md": "grilling 0.2.0\n"})
        for point in POINTS:
            with self.subTest(point=point):
                self.fail_at(point)
                self.assertEqual(snapshot(self.home), installed)
        self.install()
        self.assertEqual(self.manifest()["version"], "0.2.0")


class AbruptExit(Sandbox):
    def crash(self, point="before-publication"):
        result = self.install(check=False, MIFAL_TEST_FAIL_AT=point + ":exit")
        self.assertEqual(result.returncode, 70, result.stdout + result.stderr)
        self.assertEqual(self.manifest()["state"], "installing")

    def test_the_next_uninstall_rolls_back(self):
        self.their_grilling()
        before = snapshot(self.home)
        for point in POINTS:
            with self.subTest(point=point):
                self.crash(point)
                self.clone_mifal("uninstall")
                self.assertEqual(snapshot(self.home), before)

    def test_the_next_install_rolls_back_and_stops_without_a_terminal(self):
        self.their_grilling()
        before = snapshot(self.home)
        self.crash()
        result = self.install(check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Rolled back. Run the installer again to install.", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(snapshot(self.home), before)

    def test_the_next_install_rolls_back_and_continues_on_yes(self):
        self.their_grilling()
        before = snapshot(self.home)
        self.crash()
        result = self.run_in_terminal("/bin/bash", self.clone / "install.sh", answer="y\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Rolled back", result.stdout)
        self.assertEqual(self.manifest()["state"], "complete")
        self.mifal("uninstall")
        self.assertEqual(snapshot(self.home), before)

    def test_a_crash_during_an_upgrade_restores_the_installed_version(self):
        self.release("0.1.1", **{"old.md": "only in 0.1.1\n"})
        self.install()
        installed = snapshot(self.home)
        self.release("0.2.0", **{"old.md": None, "SKILL.md": "grilling 0.2.0\n"})
        self.crash()
        self.install(check=False)
        self.assertEqual(snapshot(self.home), installed)
        self.crash()
        self.clone_mifal("uninstall")
        self.assertFalse((self.home / ".agents").exists())

    def test_a_dry_run_after_a_crash_changes_nothing(self):
        self.crash()
        before = snapshot(self.home)
        result = self.install("--dry-run")
        self.assertIn("interrupted install", result.stdout)
        self.assertEqual(snapshot(self.home), before)
        self.clone_mifal("uninstall", "--dry-run")
        self.assertEqual(snapshot(self.home), before)

    def test_a_path_edited_after_the_interruption_is_kept_and_reported(self):
        before = snapshot(self.home)
        self.crash()
        mine = self.home / ".agents/skills/grilling/SKILL.md"
        mine.write_text("mine now\n")
        result = self.clone_mifal("uninstall")
        self.assertIn("kept ~/.agents/skills/grilling/SKILL.md: changed after the interrupted install", result.stdout)
        self.assertEqual(mine.read_text(), "mine now\n")
        self.assertEqual(changed(before, snapshot(self.home)),
                         {".agents", ".agents/skills", ".agents/skills/grilling", ".agents/skills/grilling/SKILL.md"})

    def test_a_crash_after_publication_keeps_the_new_version_and_tidies_up(self):
        self.install()
        self.release("0.2.0", **{"SKILL.md": "grilling 0.2.0\n"})
        result = self.install(check=False, MIFAL_TEST_FAIL_AT="after-publication:exit")
        self.assertEqual(result.returncode, 70)
        self.assertEqual(self.manifest()["state"], "complete")
        self.assertTrue((self.home / ".agents/mifal/.txn").is_dir())
        self.assertIn("Nothing to change", self.install().stdout)
        self.assertFalse((self.home / ".agents/mifal/.txn").exists())


class RulesFiles(Sandbox):
    def seed(self):
        self.their_grilling()
        self.harness_fakes("claude", "codex", "droid")
        (self.home / ".codex").mkdir()
        (self.home / ".codex/AGENTS.md").write_text("my codex rules\n")
        (self.home / ".claude").mkdir()
        (self.home / ".claude/CLAUDE.md").write_text("my claude rules\n")

    def test_a_failed_install_restores_every_rules_file(self):
        self.seed()
        before = snapshot(self.home)
        for point in POINTS:
            with self.subTest(point=point):
                result = self.install(check=False, MIFAL_TEST_FAIL_AT=point)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(snapshot(self.home), before)

    def test_a_crash_after_the_blocks_is_rolled_back_by_uninstall(self):
        self.seed()
        before = snapshot(self.home)
        result = self.install(check=False, MIFAL_TEST_FAIL_AT="before-publication:exit")
        self.assertEqual(result.returncode, 70)
        self.assertIn("mifal:begin", (self.home / ".codex/AGENTS.md").read_text())
        self.clone_mifal("uninstall")
        self.assertEqual(snapshot(self.home), before)

    def test_a_failed_upgrade_keeps_the_installed_blocks(self):
        self.seed()
        self.install()
        installed = snapshot(self.home)
        self.release("99.0.0")
        result = self.install(check=False, MIFAL_TEST_FAIL_AT="before-publication")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot(self.home), installed)
        self.install()
        self.assertIn("version=99.0.0", (self.home / ".codex/AGENTS.md").read_text())

    def test_a_user_edit_during_the_interrupted_install_is_kept(self):
        self.seed()
        self.install(check=False, MIFAL_TEST_FAIL_AT="before-publication:exit")
        rules = self.home / ".codex/AGENTS.md"
        rules.write_text(rules.read_text() + "added while it was broken\n")
        result = self.clone_mifal("uninstall")
        self.assertIn("kept ~/.codex/AGENTS.md: changed after the interrupted install", result.stdout)
        self.assertTrue(rules.read_text().endswith("added while it was broken\n"))


if __name__ == "__main__":
    unittest.main()
