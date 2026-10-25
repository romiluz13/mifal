"""./install.sh from a clone older than the installed version must not silently downgrade: it refuses, before any
subprocess or write, and says how to update or install on purpose."""

import unittest

import test_update
from support import Sandbox, snapshot

PENDING = "An interrupted install or update is pending"


class NoWrite:
    def refused(self, *flags):
        before, calls = snapshot(self.home), len(self.called())
        result = self.install(*flags, check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(self.called()[calls:], [], "a command ran before the refusal")
        return result.stdout + result.stderr


class Downgrade(NoWrite, Sandbox):
    def setUp(self):
        super().setUp()
        self.release("0.3.0")
        self.install()

    def test_an_older_clone_is_refused_and_nothing_is_written(self):
        self.release("0.2.9")
        text = self.refused()
        for part in ("0.2.9", "0.3.0", "mifal update", "mifal uninstall", "Nothing was changed"):
            self.assertIn(part, text)

    def test_the_dry_run_is_refused_the_same_way(self):
        self.release("0.2.9")
        self.assertIn("0.3.0", self.refused("--dry-run"))

    def test_a_malformed_version_is_refused_with_its_own_message(self):
        self.release("not-a-version")
        text = self.refused()
        self.assertIn("VERSION", text)
        self.assertNotIn("Traceback", text)

    def test_a_missing_version_file_is_refused_with_its_own_message(self):
        (self.clone / "VERSION").unlink()
        text = self.refused()
        self.assertIn("VERSION", text)
        self.assertNotIn("Traceback", text)

    def test_the_same_version_is_still_installable(self):
        self.assertIn("Nothing to change", self.install().stdout)

    def test_a_newer_clone_still_installs(self):
        self.release("0.3.1")
        self.assertEqual(self.install(check=False).returncode, 0)

    def test_an_older_version_installs_after_an_uninstall(self):
        self.mifal("uninstall")
        self.release("0.2.9")
        self.assertEqual(self.install(check=False).returncode, 0)
    def test_a_version_that_is_not_utf8_is_refused_without_a_traceback(self):
        (self.clone / "VERSION").write_bytes(bytes([255]))
        text = self.refused()
        self.assertIn("VERSION", text)
        self.assertIn("Nothing was changed", text)
        self.assertNotIn("Traceback", text)


class Recovery(NoWrite, Sandbox):
    """The guard compares with the last committed install, before tidy or any rollback can write."""

    def setUp(self):
        super().setUp()
        self.release("0.3.0")
        self.install()
        self.release("0.3.1")

    def test_after_a_crash_past_publication_the_installed_version_is_the_new_one_and_nothing_is_written(self):
        self.assertEqual(self.install(check=False, MIFAL_TEST_FAIL_AT="after-publication:exit").returncode, 70)
        self.assertEqual(self.manifest()["state"], "complete")
        self.release("0.3.0")
        text = self.refused()
        self.assertIn("0.3.1", text)
        self.assertNotIn(PENDING, text)
        self.assertTrue((self.home / ".agents/mifal/.txn").is_dir())

    def test_an_interrupted_install_refuses_an_older_clone_dry_run_and_plain_and_says_it_is_pending(self):
        self.assertEqual(self.install(check=False, MIFAL_TEST_FAIL_AT="before-publication:exit").returncode, 70)
        self.assertEqual(self.manifest()["state"], "installing")
        self.release("0.2.9")
        for flags in ((), ("--dry-run",)):
            with self.subTest(flags=flags):
                text = self.refused(*flags)
                self.assertIn(PENDING, text)
                self.assertIn("0.3.0", text)
                self.assertNotIn("Traceback", text)

    def test_a_clone_equal_to_the_previous_version_still_recovers(self):
        self.install(check=False, MIFAL_TEST_FAIL_AT="before-publication:exit")
        self.release("0.3.0")
        dry = self.install("--dry-run", check=False)
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertIn("would be rolled back", dry.stdout)
        result = self.install(check=False)
        self.assertIn("Rolled back", result.stdout)
        self.assertNotIn("Nothing was changed", result.stdout)
        self.assertEqual(self.manifest()["state"], "complete")
        self.assertEqual(self.manifest()["version"], "0.3.0")


class InterruptedUpdate(NoWrite, test_update.Update):
    def interrupt(self):
        self.previous = self.manifest()["version"]
        self.publish("a later release", **{"VERSION": "0.9.0\n"})
        result = self.update("--yes", MIFAL_TEST_FAIL_AT="after-fast-forward:exit")
        self.assertEqual(result.returncode, 70, result.stdout + result.stderr)
        self.assertEqual(self.manifest()["state"], "installing")

    def test_an_older_clone_is_refused_against_the_version_before_the_update(self):
        self.interrupt()
        self.release("0.0.1")
        text = self.refused()
        self.assertIn(PENDING, text)
        self.assertIn(self.previous, text)

    def test_a_clone_equal_to_the_version_before_the_update_still_recovers(self):
        self.interrupt()
        self.release(self.previous)
        result = self.install(check=False)
        self.assertIn("Rolled back", result.stdout)
        self.assertNotIn("Nothing was changed", result.stdout)
        self.assertEqual(self.manifest()["state"], "complete")


if __name__ == "__main__":
    unittest.main()
