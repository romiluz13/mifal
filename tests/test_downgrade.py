"""./install.sh from a clone older than the installed version must not silently downgrade: it refuses, before any
subprocess or write, and says how to update or install on purpose."""

import unittest

from support import Sandbox, snapshot


class Downgrade(Sandbox):
    def setUp(self):
        super().setUp()
        self.release("0.3.0")
        self.install()

    def refused(self, *flags):
        before, calls = snapshot(self.home), len(self.called())
        result = self.install(*flags, check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(self.called()[calls:], [], "a command ran before the refusal")
        return result.stdout + result.stderr

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


if __name__ == "__main__":
    unittest.main()
