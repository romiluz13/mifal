"""Several Homes per Harness, named with --home NAME=PATH, in a disposable HOME that mirrors a real multi-Home layout."""

import hashlib
import os
import unittest

from support import Sandbox, snapshot
from test_update import Update

SHARED = "my shared rules\n"
CLAUDE_RULES = "@~/.ai/AGENTS.md\n"
CODEX_RULES = "my codex rules\n"


class Layout:
    """A shared Personal layer file, two Claude Homes that import it and two Codex Homes with their own rules files."""

    def lay_out(self):
        (self.home / ".ai").mkdir()
        (self.home / ".ai/AGENTS.md").write_text(SHARED)
        self.claude = [self.home / ".claude", self.home / ".claude-personal"]
        self.codex = [self.home / ".codex-work", self.home / ".codex-personal"]
        for root in self.claude:
            root.mkdir()
            (root / "CLAUDE.md").write_text(CLAUDE_RULES)
        for root in self.codex:
            root.mkdir()
            (root / "AGENTS.md").write_text(CODEX_RULES)

    def flags(self, claude=None, codex=None):
        pairs = [("claude", r) for r in (self.claude if claude is None else claude)]
        pairs += [("codex", r) for r in (self.codex if codex is None else codex)]
        return [f for name, root in pairs for f in ("--home", f"{name}={root}")]

    def records(self):
        return {name: [(r["root"], r["rules"], r["status"]) for r in homes]
                for name, homes in self.manifest()["harnesses"].items()}

    def expected_records(self):
        return {"claude": [(str(r), str(r / "CLAUDE.md"), "wired") for r in self.claude],
                "codex": [(str(r), str(r / "AGENTS.md"), "wired") for r in self.codex]}


class Homes(Layout, Sandbox):
    def setUp(self):
        super().setUp()
        self.lay_out()


class Install(Homes):
    def test_two_claude_and_two_codex_homes_are_each_wired_once_and_recorded_separately(self):
        result = self.install(*self.flags())
        for root in self.claude:
            text = (root / "CLAUDE.md").read_text()
            self.assertTrue(text.startswith(CLAUDE_RULES), text)
            self.assertEqual(text.count("<!-- mifal:begin "), 1)
            self.assertIn("\n@~/.agents/mifal/AGENTS.md\n", text)
        for root in self.codex:
            text = (root / "AGENTS.md").read_text()
            self.assertTrue(text.startswith(CODEX_RULES), text)
            self.assertEqual(text.count("<!-- mifal:begin "), 1)
        self.assertEqual(self.records(), self.expected_records())
        self.assertIn("Wired: Claude Code, Codex", result.stdout)
        self.assertFalse((self.home / ".codex").exists())
        self.assertEqual((self.home / ".ai/AGENTS.md").read_text(), SHARED)

    def test_each_claude_home_has_its_own_skill_links_and_codex_reads_the_pool(self):
        self.install(*self.flags())
        pool = (self.home / ".agents/skills").resolve()
        for root in self.claude:
            self.assertEqual(os.readlink(root / "skills/grilling"), str(pool / "grilling"))
        for root in self.codex:
            self.assertFalse((root / "skills").exists())

    def test_a_name_mifal_does_not_serve_or_a_relative_path_stops_with_nothing_written(self):
        before = snapshot(self.home)
        for value, message in (
                ("gemini=" + str(self.home / ".gemini"),
                 "mifal: --home gemini=" + str(self.home / ".gemini") + ": NAME must be one of claude, codex, droid, "
                 "pi, opencode. Nothing was written."),
                ("codex", "mifal: --home codex: write it as NAME=PATH, such as codex=$HOME/.codex-work. "
                          "Nothing was written."),
                ("codex=.codex-work", "mifal: --home codex=.codex-work: PATH must be absolute, such as "
                                      "codex=$HOME/.codex-work. Nothing was written.")):
            with self.subTest(value=value):
                result = self.install("--home", value, check=False)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(message, result.stdout)
                self.assertEqual(snapshot(self.home), before)

    def test_a_home_folder_that_does_not_exist_yet_is_created_and_wired(self):
        new = self.home / "accounts/.codex-new"
        self.install("--home", f"codex={new}")
        self.assertEqual((new / "AGENTS.md").read_text().count("<!-- mifal:begin "), 1)
        self.assertEqual(self.records()["codex"], [(str(new), str(new / "AGENTS.md"), "wired")])

    def test_a_path_that_starts_with_a_tilde_is_read_from_the_home_folder(self):
        self.install("--home", "codex=~/.codex-work")
        self.assertEqual(self.records()["codex"], [(str(self.codex[0]), str(self.codex[0] / "AGENTS.md"), "wired")])

    def test_a_stop_in_one_home_stops_the_whole_run_with_nothing_written(self):
        linked = self.codex[1] / "AGENTS.md"
        linked.unlink()
        linked.symlink_to(self.home / ".ai/AGENTS.md")
        before = snapshot(self.home)
        result = self.install(*self.flags(), check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("~/.codex-personal/AGENTS.md: is a symbolic link to ~/.ai/AGENTS.md, and Mifal does not write "
                      "through a link", result.stdout)
        self.assertIn("Nothing was written.", result.stdout)
        self.assertIn("Or wire only the other Homes: ./install.sh --harness claude --home claude=" + str(self.claude[0])
                      + " --home claude=" + str(self.claude[1]) + " --harness codex --home codex=" + str(self.codex[0]),
                      result.stdout.splitlines())
        self.assertEqual(snapshot(self.home), before)

    def test_a_reinstall_naming_fewer_homes_keeps_every_recorded_home(self):
        self.install(*self.flags())
        before = snapshot(self.home)
        result = self.install(*self.flags(claude=[], codex=self.codex[:1]))
        self.assertIn("Nothing to change: Mifal is installed and current.", result.stdout)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(self.records(), self.expected_records())


class Reinstall(Homes):
    def test_a_reinstall_without_home_plans_exactly_the_recorded_homes(self):
        self.install(*self.flags())
        (self.home / ".codex").mkdir()
        (self.home / ".claude-stray").mkdir()
        before = snapshot(self.home)
        for env in ({}, {"CODEX_HOME": str(self.home / ".codex")}, {"CLAUDE_CONFIG_DIR": str(self.home / ".claude-stray")}):
            with self.subTest(env=env):
                result = self.install(**env)
                self.assertIn("Nothing to change: Mifal is installed and current.", result.stdout)
                self.assertEqual(snapshot(self.home), before)
                self.assertEqual(self.records(), self.expected_records())

    def test_a_fresh_install_without_home_serves_the_one_detected_home(self):
        self.install()
        self.assertEqual(self.records(), {"claude": [(str(self.claude[0]), str(self.claude[0] / "CLAUDE.md"), "wired")]})

    def test_the_note_for_a_shell_variable_names_the_command_that_serves_that_home(self):
        self.install(*self.flags())
        other = self.home / ".codex"
        other.mkdir()
        doctor = self.mifal("doctor", check=False, CODEX_HOME=str(other))
        note = ("note CODEX_HOME is ~/.codex, but Mifal serves ~/.codex-work and ~/.codex-personal; to serve another "
                f"home, run ./install.sh --home codex={other}")
        self.assertIn(note, doctor.stdout.splitlines())
        self.install("--home", f"codex={other}")
        self.assertEqual(self.records()["codex"], self.expected_records()["codex"]
                         + [(str(other), str(other / "AGENTS.md"), "wired")])


class Skipped(Homes):
    """Homes the install recorded as skipped, at roots only --home names; none of the Harness is wired."""

    def test_a_reinstall_keeps_a_recorded_skipped_home_and_its_folder_record(self):
        for root in self.codex:
            (root / "AGENTS.override.md").write_text("mine\n")
        self.install(*self.flags())
        self.assertEqual(self.records()["codex"],
                         [(str(r), str(r / "AGENTS.md"), "skipped") for r in self.codex])
        before = snapshot(self.home)
        result = self.install()
        self.assertIn("Nothing to change: Mifal is installed and current.", result.stdout)
        self.assertIn("skip codex: it reads ~/.codex-personal/AGENTS.override.md", result.stdout)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(self.records(), {
            "claude": [(str(r), str(r / "CLAUDE.md"), "wired") for r in self.claude],
            "codex": [(str(r), str(r / "AGENTS.md"), "skipped") for r in self.codex]})
        self.assertEqual({k for k in self.manifest()["folders"] if k.startswith("harness:")},
                         {f"harness:{n}:{r}" for n, roots in (("claude", self.claude), ("codex", self.codex))
                          for r in roots})


class Shared(Homes):
    """A second Claude Home whose skills folder is a link to the first's, as docs/INSTALL.md supports."""

    def test_both_homes_get_every_skill_link_from_one_link_per_leaf_and_uninstall_leaves_the_folder_as_it_was(self):
        (self.claude[0] / "skills").mkdir()
        (self.claude[1] / "skills").symlink_to(self.claude[0] / "skills")
        before = snapshot(self.home)
        self.install(*self.flags(claude=self.claude, codex=[]))
        pool = (self.home / ".agents/skills").resolve()
        leaf = self.claude[0] / "skills/grilling"
        self.assertTrue(leaf.is_symlink(), "the shared folder holds one Mifal link, not two")
        self.assertEqual(os.readlink(leaf), str(pool / "grilling"))
        for root in self.claude:
            self.assertEqual(os.readlink(root / "skills" / "grilling"), str(pool / "grilling"))
        spellings = {e["path"] for e in self.manifest()["entries"]
                     if e["kind"] == "symlink" and e["path"].endswith("/skills/grilling")}
        self.assertEqual(spellings, {str(r / "skills/grilling") for r in self.claude})
        after = snapshot(self.home)
        result = self.install(*self.flags(claude=self.claude, codex=[]))
        self.assertIn("Nothing to change: Mifal is installed and current.", result.stdout)
        self.assertEqual(snapshot(self.home), after)
        self.mifal("uninstall")
        self.assertEqual(snapshot(self.home), before)

    def test_doctor_does_not_call_a_served_home_that_shares_the_skills_folder_unserved(self):
        (self.claude[0] / "skills").mkdir()
        (self.claude[1] / "skills").symlink_to(self.claude[0] / "skills")
        self.install(*self.flags(claude=self.claude, codex=[]))
        doctor = self.mifal("doctor", check=False, CLAUDE_CONFIG_DIR=str(self.claude[1]))
        self.assertEqual(doctor.returncode, 0, doctor.stdout)
        self.assertNotIn("note also seen by ~/.claude-personal", doctor.stdout)
        stray = self.home / ".claude-stray"
        stray.mkdir()
        (stray / "skills").symlink_to(self.claude[0] / "skills")
        doctor = self.mifal("doctor", check=False, CLAUDE_CONFIG_DIR=str(stray))
        self.assertEqual(doctor.returncode, 0, doctor.stdout)
        self.assertIn("note also seen by ~/.claude-stray: it shares ~/.claude/skills, but Mifal does not serve "
                      "~/.claude-stray", doctor.stdout)


class Readers(Homes):
    """Homes this install does not serve that read the shared file the served Claude Homes import."""

    def test_doctor_names_each_unrecorded_home_that_links_to_or_imports_the_shared_file_and_nothing_else(self):
        self.install(*self.flags())
        shared = self.home / ".ai/AGENTS.md"
        readers = {".codex": ("AGENTS.md", None), ".claude-grove": ("CLAUDE.md", "intro\n  @~/.ai/AGENTS.md  \n"),
                   ".config/agentx": ("AGENTS.md", f"@{shared}\n"),
                   ".prose": ("CLAUDE.md", "Read ~/.ai/AGENTS.md at session start.\n"),
                   ".fenced": ("CLAUDE.md", "```\n@~/.ai/AGENTS.md\n```\n"),
                   ".other": ("CLAUDE.md", "@~/.ai/OTHER.md\n"),
                   "Dev/project": ("CLAUDE.md", "@~/.ai/AGENTS.md\n")}
        for rel, (name, text) in readers.items():
            (self.home / rel).mkdir(parents=True)
            if text is None:
                (self.home / rel / name).symlink_to(shared)
            else:
                (self.home / rel / name).write_text(text)
        (self.home / ".ai/OTHER.md").write_text("other rules\n")
        hooked = self.home / ".hooked"
        hooked.mkdir()
        for name in ("settings.json", "hooks.json"):
            (hooked / name).write_text('{"import": "@~/.ai/AGENTS.md"}\n')
            (hooked / name).chmod(0)
            (self.claude[0] / name).write_text("{}\n")
            (self.claude[0] / name).chmod(0)
        doctor = self.mifal("doctor", check=False)
        self.assertNotIn("Traceback", doctor.stdout + doctor.stderr)
        self.assertEqual([l for l in doctor.stdout.splitlines() if "not served by this install" in l],
                         ["note ~/.claude-grove reads ~/.ai/AGENTS.md, not served by this install",
                          "note ~/.codex reads ~/.ai/AGENTS.md, not served by this install",
                          "note ~/.config/agentx reads ~/.ai/AGENTS.md, not served by this install"])


class Uninstall(Homes):
    def test_uninstall_leaves_every_home_byte_for_byte_as_before_install(self):
        before = snapshot(self.home)
        self.install(*self.flags())
        self.assertNotEqual(snapshot(self.home), before)
        self.mifal("uninstall")
        self.assertEqual(snapshot(self.home), before)


class Updates(Layout, Update):
    """The four Homes installed from a clone with an origin, so a release can follow."""

    def install(self, *args, **kw):
        if not hasattr(self, "claude"):
            self.lay_out()
        return super().install(*self.flags(), *args, **kw)

    def test_an_update_moves_all_four_homes_to_the_new_release_in_one_run(self):
        guide = (self.work / "guide/AGENTS.md").read_text() + "A line the next release adds.\n"
        self.publish("a new Guide and a skill", **{"guide/AGENTS.md": guide,
                                                   "skills/newskill/SKILL.md": "---\nname: newskill\ndescription: x\n---\n"})
        result = self.update("--yes", CODEX_HOME=str(self.codex[1]))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        stamp = "guide=sha256:" + hashlib.sha256(guide.encode()).hexdigest()
        for root, rules in [(r, "CLAUDE.md") for r in self.claude] + [(r, "AGENTS.md") for r in self.codex]:
            with self.subTest(home=root.name):
                self.assertIn(f"update ~/{root.name}/{rules}", lines)
                self.assertIn(stamp, (root / rules).read_text())
        for root in self.claude:
            self.assertTrue((root / "skills/newskill").is_symlink())
        self.assertNotIn("note CODEX_HOME", result.stdout)
        self.assertEqual(self.records(), self.expected_records())

    def test_an_update_whose_guide_would_take_a_rules_file_past_32_kib_stops_with_nothing_changed(self):
        before = snapshot(self.home)
        guide = (self.work / "guide/AGENTS.md").read_text() + "x" * 30000 + "\n"
        self.publish("a Guide too long for Codex", **{"guide/AGENTS.md": guide})
        result = self.update("--yes")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        for root in self.codex:
            self.assertTrue(any(l.startswith(f"~/{root.name}/AGENTS.md would be ") and "past the 32 KiB" in l
                                for l in lines), result.stdout)
        self.assertIn("Nothing was changed.", lines)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(self.head(), self.old)

    def test_doctor_prints_one_line_per_home_and_fails_only_the_home_whose_block_was_removed(self):
        doctor = self.mifal("doctor", check=False)
        lines = doctor.stdout.splitlines()
        for root in self.claude:
            self.assertIn(f"PASS guide claude: block in ~/{root.name}/CLAUDE.md", lines)
            self.assertTrue(any(l.startswith("PASS skills claude: ") and l.endswith(f" links in ~/{root.name}/skills")
                                for l in lines), lines)
        for root in self.codex:
            self.assertIn(f"PASS guide codex: block in ~/{root.name}/AGENTS.md", lines)
        (self.codex[1] / "AGENTS.md").write_text(CODEX_RULES)
        doctor = self.mifal("doctor", check=False)
        lines = doctor.stdout.splitlines()
        self.assertEqual(doctor.returncode, 1, doctor.stdout)
        self.assertEqual([l for l in lines if l.startswith("FAIL")],
                         ["FAIL guide codex: the Mifal block in ~/.codex-personal/AGENTS.md is missing or edited"])
        self.assertIn("PASS guide codex: block in ~/.codex-work/AGENTS.md", lines)

    def test_a_shell_variable_names_a_served_home_quietly_and_another_home_with_a_note(self):
        quiet = self.mifal("doctor", check=False, CODEX_HOME=str(self.codex[1]))
        self.assertNotIn("note CODEX_HOME", quiet.stdout)
        (self.home / ".codex").mkdir()
        noted = self.mifal("doctor", check=False, CODEX_HOME=str(self.home / ".codex"))
        self.assertIn("note CODEX_HOME is ~/.codex, but Mifal serves ~/.codex-work and ~/.codex-personal; to serve "
                      f"another home, run ./install.sh --home codex={self.home / '.codex'}", noted.stdout.splitlines())


if __name__ == "__main__":
    unittest.main()
