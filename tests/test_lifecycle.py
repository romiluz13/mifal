import os
import re
import shutil
import unittest
from pathlib import Path

from support import Sandbox, changed, snapshot

TIMESTAMP = re.compile(r"(backup|mifal-saved)/\d{8}T\d{6}Z")


def planned_paths(dry_run_output):
    """The paths a dry run says it will create, change or remove, relative to HOME."""
    paths = set()
    for line in dry_run_output.splitlines():
        m = re.match(r"^(create|update|remove|link|backup|save|block) (~/\S+)", line)
        if m:
            paths.add(m.group(2)[2:])
        m = re.match(r"^(?:backup|save) ~/\S+ -> (~/\S+)", line)
        if m:
            paths.add(m.group(1)[2:])
    return paths


def normalized(paths):
    return {TIMESTAMP.sub(r"\1/T", p) for p in paths}


class DryRunEqualsWrites(Sandbox):
    def test_dry_run_lists_exactly_what_install_writes(self):
        before = snapshot(self.home)
        preview = self.install("--dry-run")
        self.assertEqual(snapshot(self.home), before, "the dry run wrote something")
        self.install()
        written = changed(before, snapshot(self.home))
        self.assertTrue(written)
        self.assertEqual(normalized(planned_paths(preview.stdout)), normalized(written))


class Reinstall(Sandbox):
    def test_second_install_changes_nothing(self):
        self.install()
        before = snapshot(self.home)
        result = self.install()
        self.assertEqual(snapshot(self.home), before)
        self.assertIn("Nothing to change", result.stdout)


class Uninstall(Sandbox):
    def seed_user_home(self):
        (self.home / ".agents/skills/someone-elses-skill").mkdir(parents=True)
        (self.home / ".agents/skills/someone-elses-skill/SKILL.md").write_text("theirs\n")
        (self.home / ".zprofile").write_text("export EDITOR=vi\n")

    def test_uninstall_restores_the_home_exactly(self):
        self.seed_user_home()
        before = snapshot(self.home)
        self.install()
        self.assertNotEqual(snapshot(self.home), before)
        self.mifal("uninstall")
        self.assertEqual(snapshot(self.home), before)

    def test_uninstall_restores_the_home_from_an_empty_start(self):
        before = snapshot(self.home)
        self.install()
        self.mifal("uninstall")
        self.assertEqual(snapshot(self.home), before)

    def test_a_colliding_skill_is_backed_up_and_restored(self):
        theirs = self.their_grilling()
        before = snapshot(self.home)
        preview = self.install("--dry-run")
        self.assertRegex(preview.stdout, r"backup ~/.agents/skills/grilling -> ~/.agents/mifal/backup/")
        self.install()
        self.assertNotEqual(theirs.read_text(), "a different grilling skill\n")
        self.mifal("uninstall")
        self.assertEqual(snapshot(self.home), before)

    def test_a_file_the_user_edited_is_kept(self):
        self.install()
        edited = self.home / ".agents/skills/grilling/SKILL.md"
        edited.write_text("my notes\n")
        result = self.mifal("uninstall")
        self.assertEqual(edited.read_text(), "my notes\n")
        self.assertIn("kept ~/.agents/skills/grilling/SKILL.md: changed since install", result.stdout)
        self.assertFalse((self.home / ".agents/mifal/install-manifest.json").exists())


    def test_a_file_the_user_added_inside_a_skill_survives(self):
        self.install()
        mine = self.home / ".agents/skills/grilling/mine.md"
        mine.write_text("my addition\n")
        self.assertIn("Nothing to change", self.install().stdout)
        self.mifal("uninstall")
        self.assertEqual(mine.read_text(), "my addition\n")
        self.assertFalse((self.home / ".agents/skills/grilling/SKILL.md").exists())

    def test_the_dry_run_changes_nothing(self):
        self.install()
        before = snapshot(self.home)
        result = self.mifal("uninstall", "--dry-run")
        self.assertIn("remove ~/.agents/skills/grilling/SKILL.md", result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_uninstall_works_after_the_clone_is_deleted(self):
        before = snapshot(self.home)
        self.install()
        shutil.rmtree(self.clone)
        self.mifal("uninstall")
        self.assertEqual(snapshot(self.home), before)


class EditProtection(Sandbox):
    def refused(self, path):
        before = snapshot(self.home)
        result = self.install(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(path, result.stdout)
        self.assertIn("--overwrite-edits", result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_a_reinstall_over_an_edited_file_stops_before_any_write(self):
        self.install()
        (self.home / ".agents/skills/grilling/SKILL.md").write_text("my notes\n")
        self.refused("~/.agents/skills/grilling/SKILL.md")

    def test_a_reinstall_that_reserves_a_name_you_already_use_stops_until_overwrite_edits(self):
        self.install()
        theirs = self.home / ".agents/skills/commit/SKILL.md"
        theirs.parent.mkdir(parents=True)
        theirs.write_text("my commit skill\n")
        (self.clone / "skills/commit").mkdir()
        (self.clone / "skills/commit/SKILL.md").write_text("mifal commit\n")
        self.refused("~/.agents/skills/commit")
        self.assertEqual(theirs.read_text(), "my commit skill\n")
        result = self.install("--overwrite-edits")
        self.assertRegex(result.stdout, r"backup ~/.agents/skills/commit -> ~/.agents/mifal/backup/")
        self.assertEqual(theirs.read_text(), "mifal commit\n")
        self.mifal("uninstall")
        self.assertEqual(theirs.read_text(), "my commit skill\n")

    def test_overwrite_edits_saves_a_copy_first(self):
        self.install()
        edited = self.home / ".agents/skills/grilling/SKILL.md"
        edited.write_text("my notes\n")
        preview = self.install("--overwrite-edits", "--dry-run")
        before = snapshot(self.home)
        result = self.install("--overwrite-edits")
        self.assertRegex(result.stdout, r"save ~/.agents/skills/grilling/SKILL.md -> ~/.agents/mifal-saved/")
        self.assertEqual(normalized(planned_paths(preview.stdout)), normalized(changed(before, snapshot(self.home))))
        self.assertEqual(edited.read_bytes(), (self.clone / "skills/grilling/SKILL.md").read_bytes())
        saved = list((self.home / ".agents/mifal-saved").rglob("SKILL.md"))
        self.assertEqual([p.read_text() for p in saved], ["my notes\n"])
        result = self.mifal("uninstall")
        self.assertIn("~/.agents/mifal-saved/", result.stdout)
        self.assertEqual([p.read_text() for p in saved], ["my notes\n"])

    def test_a_symlink_in_place_of_an_owned_file_is_an_edit(self):
        self.install()
        owned = self.home / ".agents/skills/grilling/SKILL.md"
        same = self.home / "same.md"
        same.write_bytes(owned.read_bytes())
        owned.unlink()
        owned.symlink_to(same)
        self.refused("~/.agents/skills/grilling/SKILL.md")
        result = self.mifal("uninstall")
        self.assertIn("kept ~/.agents/skills/grilling/SKILL.md", result.stdout)
        self.assertTrue(owned.is_symlink())

    def test_a_folder_in_place_of_an_owned_file_is_an_edit(self):
        self.install()
        owned = self.home / ".agents/skills/grilling/SKILL.md"
        owned.unlink()
        owned.mkdir()
        self.refused("~/.agents/skills/grilling/SKILL.md")


class Upgrade(Sandbox):
    def test_original_then_two_releases_then_uninstall_restores_the_original(self):
        self.their_grilling()
        original = snapshot(self.home)
        self.release("0.1.1", **{"old.md": "only in 0.1.1\n"})
        self.install()
        self.release("0.2.0", **{"old.md": None, "SKILL.md": "grilling 0.2.0\n"})
        result = self.install()
        self.assertIn("remove ~/.agents/skills/grilling/old.md", result.stdout)
        self.assertIn("update ~/.agents/skills/grilling/SKILL.md", result.stdout)
        self.assertFalse((self.home / ".agents/skills/grilling/old.md").exists())
        self.assertEqual((self.home / ".agents/skills/grilling/SKILL.md").read_text(), "grilling 0.2.0\n")
        self.mifal("uninstall")
        self.assertEqual(snapshot(self.home), original)

    def test_an_edited_obsolete_file_is_kept_and_reported(self):
        self.release("0.1.1", **{"old.md": "only in 0.1.1\n"})
        self.install()
        old = self.home / ".agents/skills/grilling/old.md"
        old.write_text("I changed this\n")
        self.release("0.2.0", **{"old.md": None})
        result = self.install()
        self.assertIn("keep ~/.agents/skills/grilling/old.md", result.stdout)
        self.assertNotIn(str(old), {e["path"] for e in self.manifest()["entries"]})
        self.mifal("uninstall")
        self.assertEqual(old.read_text(), "I changed this\n")


class LinkedPool(Sandbox):
    def test_a_linked_pool_is_written_through_its_realpath(self):
        real = self.home / "shared/skills"
        real.mkdir(parents=True)
        (self.home / ".agents").mkdir()
        (self.home / ".agents/skills").symlink_to(real)
        before = snapshot(self.home)
        preview = self.install("--dry-run")
        self.assertIn("note ~/.agents/skills is a link to ~/shared/skills", preview.stdout)
        self.assertIn("create ~/shared/skills/grilling/SKILL.md", preview.stdout)
        self.install()
        self.assertEqual(normalized(planned_paths(preview.stdout)), normalized(changed(before, snapshot(self.home))))
        paths = {e["path"] for e in self.manifest()["entries"]}
        self.assertIn(str(real / "grilling/SKILL.md"), paths)
        self.assertFalse([p for p in paths if "/.agents/skills/" in p])
        self.mifal("uninstall")
        self.assertEqual(snapshot(self.home), before)


class LeafLinks(Sandbox):
    def test_a_foreign_mifal_link_is_moved_as_the_link(self):
        tool = self.home / "tools/other-mifal"
        tool.parent.mkdir()
        tool.write_text("#!/bin/sh\necho another tool\n")
        (self.home / ".local/bin").mkdir(parents=True)
        link = self.home / ".local/bin/mifal"
        link.symlink_to(tool)
        before = snapshot(self.home)
        self.assertRegex(self.install("--dry-run").stdout, r"backup ~/.local/bin/mifal -> ~/.agents/mifal/backup/")
        self.install()
        self.assertEqual(tool.read_text(), "#!/bin/sh\necho another tool\n")
        self.assertEqual(Path(os.readlink(link)), self.home / ".agents/mifal/bin/mifal")
        self.mifal("uninstall")
        self.assertEqual(snapshot(self.home), before)

    def test_a_skill_folder_that_is_a_link_is_moved_as_the_link(self):
        theirs = self.home / "my-skills/grilling"
        theirs.mkdir(parents=True)
        (theirs / "SKILL.md").write_text("mine\n")
        (self.home / ".agents/skills").mkdir(parents=True)
        (self.home / ".agents/skills/grilling").symlink_to(theirs)
        before = snapshot(self.home)
        self.install()
        self.assertEqual((theirs / "SKILL.md").read_text(), "mine\n")
        self.assertEqual(sorted(p.name for p in theirs.iterdir()), ["SKILL.md"])
        self.assertFalse((self.home / ".agents/skills/grilling").is_symlink())
        self.mifal("uninstall")
        self.assertEqual(snapshot(self.home), before)

    def test_a_retargeted_owned_link_is_an_edit(self):
        self.install()
        link = self.home / ".local/bin/mifal"
        other = self.home / "other-tool"
        other.write_text("other\n")
        link.unlink()
        link.symlink_to(other)
        before = snapshot(self.home)
        result = self.install(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("~/.local/bin/mifal: changed since Mifal wrote it", result.stdout)
        self.assertEqual(snapshot(self.home), before)
        result = self.clone_mifal("uninstall")
        self.assertIn("kept ~/.local/bin/mifal", result.stdout)
        self.assertEqual(Path(os.readlink(link)), other)


class PathHint(Sandbox):
    def test_the_hint_appears_only_when_the_bin_folder_is_off_path(self):
        bindir = str(self.home / ".local/bin")
        self.assertIn(f"Add {bindir} to your PATH", self.install().stdout)
        self.mifal("uninstall")
        on_path = self.install(PATH=":".join([bindir, str(self.fakebin), "/usr/bin", "/bin"]))
        self.assertNotIn("to your PATH", on_path.stdout)


class InstalledCommand(Sandbox):
    def test_mifal_runs_from_the_install_after_the_clone_is_deleted(self):
        self.install()
        link = self.home / ".local/bin/mifal"
        self.assertEqual(Path(os.readlink(link)), self.home / ".agents/mifal/bin/mifal")
        shutil.rmtree(self.clone)
        self.assertRegex(self.mifal("version").stdout, r"^mifal \d+\.\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
