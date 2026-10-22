"""What Mifal must never destroy: unowned files, links the user made, bytes outside its block, edits made mid-prompt."""
import os
import select
import shutil
import subprocess
import time
import unittest

from support import Sandbox, snapshot
from test_update import Update


def files_under(folder):
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


class Ownership(Sandbox):
    def test_a_transaction_folder_without_a_manifest_is_left_alone(self):
        foreign = self.home / ".agents/mifal/.txn/keep.txt"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("unrelated work\n")
        result = self.install(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("holds no Manifest", result.stdout + result.stderr)
        self.assertEqual(foreign.read_text(), "unrelated work\n")

    def test_a_file_at_the_old_temporary_name_is_left_alone(self):
        sibling = self.home / ".codex/AGENTS.md.mifal-tmp"
        sibling.parent.mkdir(parents=True)
        sibling.write_text("unrelated work\n")
        self.install("--harness", "codex")
        self.assertEqual(sibling.read_text(), "unrelated work\n")
        self.assertIn("mifal:begin", (self.home / ".codex/AGENTS.md").read_text())
        self.mifal("uninstall")
        self.assertEqual(sibling.read_text(), "unrelated work\n")

    def test_a_link_at_the_old_temporary_name_is_never_written_through(self):
        rules = self.home / ".codex/AGENTS.md"
        rules.parent.mkdir(parents=True)
        target = self.root / "foreign-policy.md"
        target.write_text("foreign policy\n")
        rules.with_name(rules.name + ".mifal-tmp").symlink_to(target)
        self.install("--harness", "codex")
        self.assertEqual(target.read_text(), "foreign policy\n")
        self.assertFalse(rules.is_symlink())
        self.assertIn("mifal:begin", rules.read_text())

    def test_no_temporary_file_is_left_after_install_or_uninstall(self):
        self.harness_fakes("claude", "codex")
        self.install()
        self.mifal("uninstall")
        self.assertEqual([p for p in self.home.rglob("*") if "tmp" in p.name], [])

    def test_recovery_keeps_a_file_planted_where_a_temporary_file_could_be(self):
        result = self.install("--harness", "codex", MIFAL_TEST_FAIL_AT="after-write:exit", check=False)
        self.assertEqual(result.returncode, 70)
        rules = self.home / ".codex/AGENTS.md"
        self.assertFalse(rules.exists())
        rules.parent.mkdir(parents=True, exist_ok=True)
        names = {".AGENTS.md.mifal-" + self.manifest().get("token", "t") + ".tmp", "AGENTS.md.mifal-tmp"}
        for name in names:
            (rules.parent / name).write_text("unrelated work created after the interruption\n")
        self.clone_mifal("uninstall", check=False)
        for name in names:
            self.assertEqual((rules.parent / name).read_text(), "unrelated work created after the interruption\n")


class ChangedFolders(Sandbox):
    def test_a_skill_folder_replaced_by_a_link_is_kept_and_its_referent_untouched(self):
        self.install()
        owned = self.home / ".agents/skills/grilling"
        foreign = self.root / "foreign-grilling"
        shutil.move(str(owned), str(foreign))
        owned.symlink_to(foreign, target_is_directory=True)
        before = files_under(foreign)
        result = self.mifal("uninstall", check=False)
        self.assertEqual(files_under(foreign), before)
        self.assertTrue(owned.is_symlink())
        self.assertIn("kept ~/.agents/skills/grilling: it is a link now", result.stdout)

    def test_recovery_refuses_a_pool_moved_after_a_crash(self):
        result = self.install(MIFAL_TEST_FAIL_AT="before-publication:exit", check=False)
        self.assertEqual(result.returncode, 70)
        pool = self.home / ".agents/skills"
        foreign = self.root / "foreign-pool"
        shutil.move(str(pool), str(foreign))
        pool.symlink_to(foreign, target_is_directory=True)
        before = files_under(foreign)
        result = self.clone_mifal("uninstall", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(files_under(foreign), before)
        self.assertIn("~/.agents/skills", result.stdout)


class RulesFiles(Sandbox):
    def test_a_rules_file_the_user_turned_into_a_link_is_kept(self):
        rules = self.home / ".codex/AGENTS.md"
        rules.parent.mkdir(parents=True)
        rules.write_text("my rules\n")
        self.install("--harness", "codex")
        target = self.home / "policy.md"
        rules.rename(target)
        rules.symlink_to(target)
        held = target.read_bytes()
        result = self.mifal("uninstall", check=False)
        self.assertTrue(rules.is_symlink())
        self.assertEqual(target.read_bytes(), held)
        self.assertIn("kept the Mifal block in ~/.codex/AGENTS.md", result.stdout)

    def test_crlf_bytes_outside_the_block_survive_install_and_uninstall(self):
        rules = self.home / ".codex/AGENTS.md"
        rules.parent.mkdir(parents=True)
        original = b"first user line\r\nsecond user line\r\n"
        rules.write_bytes(original)
        self.install("--harness", "codex")
        self.assertTrue(rules.read_bytes().startswith(original))
        self.mifal("uninstall")
        self.assertEqual(rules.read_bytes(), original)

    def test_a_reinstall_keeps_crlf_bytes_after_the_block(self):
        rules = self.home / ".codex/AGENTS.md"
        rules.parent.mkdir(parents=True)
        rules.write_bytes(b"before\r\n")
        self.install("--harness", "codex")
        rules.write_bytes(rules.read_bytes() + b"after\r\n")
        self.release("0.1.1")
        self.install("--harness", "codex")
        self.assertTrue(rules.read_bytes().startswith(b"before\r\n"))
        self.assertTrue(rules.read_bytes().endswith(b"after\r\n"))
        self.mifal("uninstall")
        self.assertEqual(rules.read_bytes(), b"before\r\nafter\r\n")


class Precedence(Sandbox):
    def test_opencode_reads_its_fallback_unless_the_flag_is_true_or_1(self):
        fallback = self.home / ".claude/CLAUDE.md"
        fallback.parent.mkdir(parents=True)
        fallback.write_text("my active fallback policy\n")
        rules = self.home / ".config/opencode/AGENTS.md"
        for value, wired in (("false", False), ("0", False), ("", False), ("TRUE", True), ("1", True)):
            with self.subTest(OPENCODE_DISABLE_CLAUDE_CODE=value):
                result = self.install("--harness", "opencode", "--dry-run", OPENCODE_DISABLE_CLAUDE_CODE=value)
                self.assertEqual("skip opencode" not in result.stdout, wired, result.stdout)
        result = self.install("--harness", "opencode", OPENCODE_DISABLE_CLAUDE_CODE_PROMPT="no")
        self.assertIn("skip opencode", result.stdout)
        self.assertFalse(rules.exists())

    def test_doctor_fails_with_the_fix_when_an_override_was_there_before_install(self):
        override = self.home / ".codex/AGENTS.override.md"
        override.parent.mkdir(parents=True)
        override.write_text("my override\n")
        self.install("--harness", "codex")
        result = self.mifal("doctor", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertRegex(result.stdout, r"(?m)^FAIL guide codex: .*AGENTS\.override\.md")
        self.assertRegex(result.stdout, r"(?m)^     fix: ")


class Approval(Update):
    def test_an_edit_made_while_the_update_waits_for_approval_stops_it(self):
        victim = self.home / ".agents/skills/grilling/SKILL.md"
        self.publish("change owned skill", **{"skills/grilling/SKILL.md": "candidate replacement\n"})
        primary, secondary = os.openpty()
        process = subprocess.Popen(["/bin/bash", str(self.home / ".local/bin/mifal"), "update"],
                                   cwd=self.root, env=self.env(), stdin=secondary,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = b""
        try:
            deadline = time.monotonic() + 45
            while b"Apply " not in output and time.monotonic() < deadline:
                if select.select([process.stdout], [], [], 0.2)[0]:
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    output += chunk
            self.assertIn(b"Apply ", output, output.decode(errors="replace"))
            victim.write_text("user edit during approval\n")
            installed = snapshot(self.home)
            os.write(primary, b"y\n")
            tail, _ = process.communicate(timeout=120)
            output += tail
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(primary)
            os.close(secondary)
        self.assertNotEqual(process.returncode, 0, output.decode(errors="replace"))
        self.assertIn("changed while", output.decode(errors="replace"))
        self.assertEqual(victim.read_text(), "user edit during approval\n")
        self.assertEqual(snapshot(self.home), installed)
        self.assertEqual(self.head(), self.old)


class LinkedRulesFile(Sandbox):
    """An agent's rules file that is a symbolic link: refuse, write nothing, and say honestly how to go on."""

    def linked(self, outside, name="codex"):
        rules = self.home / (".codex/AGENTS.md" if name == "codex" else ".claude/CLAUDE.md")
        rules.parent.mkdir(parents=True, exist_ok=True)
        target = (self.root / "dotfiles" if outside else self.home) / "policy.md"
        target.parent.mkdir(exist_ok=True)
        target.write_text("my rules\n")
        rules.symlink_to(target)
        return rules, target

    def refused(self, outside, *args):
        self.harness_fakes("codex", "claude")
        rules, target = self.linked(outside)
        before = snapshot(self.home)
        held = target.read_bytes()
        result = self.install(*args, check=False)
        text = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, text)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(target.read_bytes(), held)
        self.assertTrue(rules.is_symlink())
        self.assertIn("~/.codex/AGENTS.md", text)
        self.assertIn("symbolic link", text)
        self.assertIn(str(target) if outside else "~/policy.md", text)
        self.assertIn("To wire that agent, replace the link with a regular file and run again; "
                      f"the agent then reads its own copy, not {str(target) if outside else '~/policy.md'}.", text)
        self.assertIn("Or wire only the other agents: ./install.sh --harness claude", text)
        self.assertNotIn("--overwrite-edits", text)
        self.assertNotIn("cp -L", text)
        self.assertEqual(text.count("does not write through a link"), 1)
        return text

    def test_install_refuses_and_names_the_link_and_the_two_ways_out(self):
        for outside in (False, True):
            for args in ((), ("--dry-run",), ("--overwrite-edits",)):
                with self.subTest(outside=outside, args=args):
                    self.setUp()
                    self.refused(outside, *args)

    def test_with_no_other_agent_to_wire_only_replacing_the_link_is_offered(self):
        self.harness_fakes("codex")
        rules, target = self.linked(False)
        result = self.install(check=False)
        text = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symbolic link", text)
        self.assertIn("To wire that agent, replace the link with a regular file", text)
        self.assertNotIn("--harness", text)
        self.assertNotIn("other agents", text)
        self.assertNotIn("--overwrite-edits", text)

    def test_a_folder_in_place_of_a_rules_file_is_called_a_folder(self):
        self.harness_fakes("codex", "claude")
        (self.home / ".codex/AGENTS.md").mkdir(parents=True)
        result = self.install(check=False)
        text = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("~/.codex/AGENTS.md", text)
        self.assertIn("is a folder", text)
        self.assertIn("To wire that agent, replace it with a regular file and run again.", text)
        self.assertNotIn("its own copy", text)
        self.assertNotIn("symbolic link", text)
        self.assertNotIn("--overwrite-edits", text)

    def test_a_link_beside_an_edited_block_keeps_the_overwrite_advice_for_the_block(self):
        self.harness_fakes("claude")
        self.install()
        claude = self.home / ".claude/CLAUDE.md"
        claude.write_text(claude.read_text().replace("@~/.agents/mifal/AGENTS.md", "@~/elsewhere.md"))
        self.harness_fakes("codex")
        self.linked(False)
        result = self.install(check=False)
        text = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symbolic link", text)
        self.assertIn("its Mifal block changed since install", text)
        self.assertIn("--overwrite-edits", text)


class LinkedRulesFileOnUpdate(Update):
    def test_update_names_a_rules_file_the_user_turned_into_a_link(self):
        (self.home / ".codex").mkdir()
        self.fake("codex", "")
        self.install("--harness", "codex")
        rules = self.home / ".codex/AGENTS.md"
        target = self.home / "policy.md"
        rules.rename(target)
        rules.symlink_to(target)
        self.publish("a new release", VERSION="9.9.9\n")
        before, held = snapshot(self.home), target.read_bytes()
        result = self.update("--yes")
        text = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, text)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(target.read_bytes(), held)
        self.assertIn("~/.codex/AGENTS.md", text)
        self.assertIn("symbolic link to ~/policy.md", text)
        self.assertIn("To wire that agent, replace the link with a regular file and run again; "
                      "the agent then reads its own copy, not ~/policy.md.", text)
        self.assertNotIn("--harness", text)
        self.assertNotIn("--overwrite-edits", text)
        self.assertNotIn("cp -L", text)


if __name__ == "__main__":
    unittest.main()
