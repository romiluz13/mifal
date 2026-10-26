"""An update that finds the installed revision is already the candidate but the install lacks files that revision's
engine installs (what a 0.2.3 update leaves behind) repairs it, and refuses to when it cannot do so cleanly."""

import unittest

from support import snapshot
import test_update

LICENCES = (".agents/mifal/NOTICE", ".agents/mifal/third_party/provenance.json",
            ".agents/mifal/third_party/licenses/herdr.txt")


class Repair(test_update.Update):
    def setUp(self):
        super().setUp()
        self.drop_licences()

    def paths_owned(self):
        return {e["path"] for e in self.manifest()["entries"]}

    def test_update_yes_installs_and_records_the_missing_files_and_doctor_is_clean(self):  # a
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("this install is missing 16 file(s) this version installs", result.stdout)
        for rel in LICENCES:
            self.assertTrue((self.home / rel).is_file(), rel)
            self.assertIn(str((self.home / rel).resolve()), self.paths_owned())
        doctor = self.mifal("doctor", check=False)
        self.assertEqual(doctor.returncode, 0, doctor.stdout)
        self.assertNotIn("WARN engine", doctor.stdout)
        after = snapshot(self.home)
        self.assertIn("up to date", self.update("--yes").stdout)
        self.assertEqual(snapshot(self.home), after)

    def test_without_a_terminal_and_without_yes_it_is_not_applied(self):  # b
        result = self.update()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Not applied", result.stdout)
        self.assertEqual(snapshot(self.home), self.installed)

    def test_a_user_edit_to_an_owned_file_blocks_the_repair(self):  # c
        (self.home / ".agents/mifal/LICENSE").write_text("edited\n")
        before = snapshot(self.home)
        result = self.update("--yes")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Nothing was changed", result.stdout)
        self.assertEqual(snapshot(self.home), before)
        self.assertFalse((self.home / ".agents/mifal/NOTICE").exists())

    def test_declining_the_prompt_changes_nothing(self):  # d
        result = self.update_in_terminal("n\n")
        self.assertIn("this install is missing 16 file(s)", result.stdout)
        self.assertIn("Not applied", result.stdout)
        self.assertEqual(snapshot(self.home), self.installed)

    def test_a_failure_before_publication_restores_everything_and_a_retry_succeeds(self):  # e
        result = self.update("--yes", MIFAL_TEST_FAIL_AT="fast-forward")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(snapshot(self.home), self.installed)
        self.assertEqual(self.update("--yes").returncode, 0)
        self.assertTrue((self.home / ".agents/mifal/NOTICE").is_file())

    def test_the_recorded_revision_and_the_clone_head_do_not_change(self):  # f
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.manifest()["source"]["revision"], self.old)
        self.assertEqual(self.head(), self.old)
        self.assertTrue((self.home / ".agents/mifal/NOTICE").is_file())


class Unchanged(test_update.Update):
    """Green before and after: an install that is complete stays a no-op."""

    def test_a_complete_install_with_an_edited_owned_file_is_still_up_to_date(self):
        (self.home / ".agents/mifal/LICENSE").write_text("edited\n")
        before = snapshot(self.home)
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("up to date", result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_an_agent_that_became_discoverable_after_the_install_is_not_a_reason_to_update(self):
        self.harness_fakes("codex")
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("up to date", result.stdout)
        self.assertEqual(snapshot(self.home), self.installed)


class RepairBeyondTheRelease(test_update.Update):
    tag, cut = test_update.Releases.tag, test_update.Releases.cut

    def test_a_clone_pulled_past_the_installed_release_keeps_its_head_through_the_repair(self):  # f
        release = self.cut("0.2.0")
        self.assertEqual(self.update("--yes").returncode, 0)
        self.publish("after the release", **{"UNRELEASED": "x\n"})
        self.git(self.clone, "pull", "-q", "--ff-only")
        beyond = self.head()
        self.assertNotEqual(beyond, release)
        self.drop_licences()
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("this install is missing 16 file(s)", result.stdout)
        self.assertEqual(self.head(), beyond)
        self.assertEqual(self.manifest()["source"]["revision"], release)
        self.assertTrue((self.home / ".agents/mifal/NOTICE").is_file())


if __name__ == "__main__":
    unittest.main()
