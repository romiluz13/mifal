"""A Manifest only acts on the home that recorded it: another home's engine, reached through a link, is refused."""

import json
import os
import unittest

from support import MANIFEST, snapshot
from test_update import Update

REFUSED = "belongs to the Mifal install for"


class Helpers:
    def text(self, result):
        return result.stdout + result.stderr

    def works(self, result):
        self.assertEqual(result.returncode, 0, self.text(result))


class Foreign(Helpers, Update):
    """Home A (self.home) has a Mifal install; home B is another home whose engine folder, or a parent of it,
    is a link into A's."""

    def install(self, *args, **kw):
        self.harness_fakes("codex")
        return super().install("--harness", "codex", *args, **kw)

    def make_b(self, link="engine"):
        self.b = self.root / "home-b"
        (self.b / ".agents").mkdir(parents=True) if link == "engine" else self.b.mkdir()
        if link == "engine":
            (self.b / ".agents/mifal").symlink_to(self.home / ".agents/mifal")
        else:
            (self.b / ".agents").symlink_to(self.home / ".agents")
        return self.b

    def as_b(self, *args, **kw):
        return self.mifal(*args, HOME=str(self.b), check=False, **kw)

    def assert_refused(self, result):
        self.assertNotEqual(result.returncode, 0, self.text(result))
        self.assertIn(REFUSED, self.text(result))
        self.assertIn("Nothing was changed.", self.text(result))

    def tamper(self, **changes):
        path = self.home / MANIFEST
        data = json.loads(path.read_text())
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        path.write_text(json.dumps(data))


class Uninstall(Foreign):
    def test_uninstall_from_another_home_is_refused_and_changes_nothing(self):  # a
        self.make_b()
        before = snapshot(self.home)
        result = self.as_b("uninstall")
        self.assert_refused(result)
        self.assertEqual(snapshot(self.home), before)
        self.assertTrue((self.home / MANIFEST).exists())
        self.assertIn("mifal:begin", (self.home / ".codex/AGENTS.md").read_text())

    def test_the_message_names_the_recorded_home_and_this_home(self):
        self.make_b()
        text = self.text(self.as_b("uninstall"))
        self.assertIn(f"for {self.home}", text)
        self.assertIn(f"not this home ({self.b})", text)


class Install(Foreign):
    def test_a_refused_install_leaves_the_other_homes_txn_folder(self):  # b
        sentinel = self.home / ".agents/mifal/.txn/sentinel"
        sentinel.parent.mkdir()
        sentinel.write_text("x")
        self.make_b()
        result = self.install(HOME=str(self.b), check=False)
        self.assertTrue(sentinel.exists(), "the other home's .txn folder was removed: " + self.text(result))
        self.assert_refused(result)

    def test_the_dry_run_is_refused_too_and_leaves_the_txn_folder(self):  # b2
        sentinel = self.home / ".agents/mifal/.txn/sentinel"
        sentinel.parent.mkdir()
        sentinel.write_text("x")
        self.make_b()
        result = self.install("--dry-run", HOME=str(self.b), check=False)
        self.assertNotEqual(result.returncode, 0, self.text(result))
        self.assertTrue(sentinel.exists())


class UpdateAndDoctor(Foreign):
    def test_update_and_doctor_from_another_home_are_refused_and_change_nothing(self):  # c
        self.make_b()
        before = snapshot(self.home)
        for command in ("update", "doctor"):
            with self.subTest(command=command):
                self.assert_refused(self.as_b(command))
                self.assertEqual(snapshot(self.home), before)


class Links(Foreign):
    def test_the_message_names_the_engine_link(self):
        self.make_b("engine")
        self.assertIn("Remove the link ~/.agents/mifal if it should not lead there.", self.text(self.as_b("uninstall")))

    def test_the_message_names_a_parent_link(self):
        self.make_b("parent")
        text = self.text(self.as_b("uninstall"))
        self.assertIn("Remove the link ~/.agents if it should not lead there.", text)
        self.assertNotIn("Remove the link ~/.agents/mifal", text)

    def test_without_a_link_the_message_says_a_renamed_home_is_not_acted_on(self):
        moved = self.root / "home-moved"
        self.home.rename(moved)
        result = self.clone_mifal("uninstall", HOME=str(moved), check=False)
        self.assert_refused(result)
        self.assertNotIn("Remove the link", self.text(result))
        self.assertIn("If this home folder was renamed or moved", self.text(result))


class NoHomeField(Foreign):
    """e: a Manifest whose home is missing or not a string. Each case has its own install, because a command that is not
    refused (as on 0.2.3) may remove it."""

    def refused_by(self, command, bad):
        self.tamper(home=bad)
        before = snapshot(self.home)
        result = self.install(check=False) if command == "install" else self.mifal(command, check=False)
        self.assertNotEqual(result.returncode, 0, self.text(result))
        self.assertIn('has no usable "home" field. Nothing was changed.', self.text(result))
        self.assertEqual(snapshot(self.home), before)


for _command in ("install", "update", "uninstall", "doctor"):
    for _name, _bad in (("missing", None), ("a_number", 7)):
        setattr(NoHomeField, f"test_{_command}_refuses_a_manifest_whose_home_is_{_name}",
                lambda self, c=_command, b=_bad: self.refused_by(c, b))


class StillWorks(Foreign):
    def test_the_same_home_through_a_symlinked_home_path_still_works(self):  # d
        link = self.root / "link-to-a"
        link.symlink_to(self.home)
        self.works(self.mifal("doctor", HOME=str(link), check=False))
        self.works(self.update("--yes", HOME=str(link)))
        self.works(self.install(HOME=str(link), check=False))
        self.works(self.mifal("uninstall", HOME=str(link), check=False))
        self.assertFalse((self.home / MANIFEST).exists())

    def test_the_same_home_spelled_in_another_case_still_works(self):  # g
        other = self.root / "HOME"
        if not (other.exists() and os.path.samefile(other, self.home)):
            self.skipTest("this volume is case-sensitive")
        # The doctor's layout check compares the command link's text with a path in the new spelling, so at 0.2.3 it
        # reports FAIL layout and the install stops on its recorded paths; what must hold is that the guard does not refuse it.
        self.assertNotIn(REFUSED, self.text(self.mifal("doctor", HOME=str(other), check=False)))
        self.works(self.update("--yes", HOME=str(other)))
        self.assertNotIn(REFUSED, self.text(self.install(HOME=str(other), check=False)))
        self.works(self.mifal("uninstall", HOME=str(other), check=False))
        self.assertFalse((self.home / MANIFEST).exists())

    def test_the_dry_run_of_a_matching_home_still_works(self):
        self.works(self.install("--dry-run", check=False))


class OutsideRoot(Helpers, Update):
    def test_an_install_with_a_root_outside_the_home_still_updates_and_uninstalls(self):  # f
        self.outside = self.root / "outside-claude"
        self.outside.mkdir()
        self.harness_fakes("claude")
        self.mifal("uninstall")
        result = self.install("--harness", "claude", "--allow-root-outside-home", CLAUDE_CONFIG_DIR=str(self.outside),
                              outside=("CLAUDE_CONFIG_DIR",), check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.works(self.update("--yes"))
        self.works(self.mifal("doctor", check=False))
        self.works(self.mifal("uninstall", check=False))
        self.assertFalse((self.home / MANIFEST).exists())


if __name__ == "__main__":
    unittest.main()
