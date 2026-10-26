import os
import re
import sys
import unittest
from pathlib import Path

from support import REPO, Sandbox, changed, snapshot
from test_content import denied
from test_lifecycle import normalized, planned_paths

sys.path.insert(0, str(REPO / "lib"))
from mifal import harness  # noqa: E402

BLOCK = re.compile(r"<!-- mifal:begin [^\n]*-->\n.*?<!-- mifal:end -->\n", re.S)
IMPORT = "@~/.agents/mifal/AGENTS.md"
RULES = {
    "claude": ".claude/CLAUDE.md",
    "codex": ".codex/AGENTS.md",
    "droid": ".factory/AGENTS.md",
    "pi": ".pi/agent/AGENTS.md",
    "opencode": ".config/opencode/AGENTS.md",
}


class Wiring(Sandbox):
    def guide(self):
        return (self.home / ".agents/mifal/AGENTS.md").read_text()

    def blocks(self, rel):
        path = self.home / rel
        return BLOCK.findall(path.read_text()) if path.exists() else []

    def wired(self):
        return {name for name, rel in RULES.items() if self.blocks(rel)}

    def harness_calls(self):
        return [c for c in self.called() if c.split()[0] in RULES]


class EachHarness(Wiring):
    def test_only_the_detected_harness_is_wired(self):
        for name in RULES:
            with self.subTest(harness=name):
                self.setUp()
                self.harness_fakes(name)
                self.install()
                self.assertEqual(self.wired(), {name})
                block = self.blocks(RULES[name])[0]
                if name == "claude":
                    self.assertIn("\n" + IMPORT + "\n", block)
                    link = self.home / ".claude/skills/tdd"
                    self.assertEqual(os.readlink(link), os.path.realpath(self.home / ".agents/skills/tdd"))
                else:
                    self.assertIn(self.guide().strip(), block)
                self.assertFalse(name != "claude" and (self.home / ".claude/skills").exists())
                self.assertEqual(self.harness_calls(), [])

    def test_the_manifest_records_each_wired_harness_and_its_root(self):
        self.harness_fakes(*RULES)
        self.install()
        harnesses = self.manifest()["harnesses"]
        for name, rel in RULES.items():
            with self.subTest(harness=name):
                self.assertEqual(harnesses[name][0]["rules"], os.path.realpath(self.home / rel))
                self.assertEqual(harnesses[name][0]["status"], "wired")

    def test_dry_run_lists_every_block_and_link_it_writes(self):
        self.harness_fakes(*RULES)
        before = snapshot(self.home)
        preview = self.install("--dry-run")
        self.assertEqual(snapshot(self.home), before)
        self.install()
        self.assertEqual(normalized(planned_paths(preview.stdout)), normalized(changed(before, snapshot(self.home))))

    def test_uninstall_returns_every_harness_folder_to_its_state_before_install(self):
        self.harness_fakes(*RULES)
        (self.home / ".codex").mkdir()
        (self.home / ".codex/AGENTS.md").write_text("# My Codex rules\n")
        (self.home / ".claude").mkdir()
        before = snapshot(self.home)
        self.install()
        self.mifal("uninstall")
        self.assertEqual(snapshot(self.home), before)


class UserContent(Wiring):
    def test_content_before_and_after_the_block_survives_reinstall_and_uninstall(self):
        self.harness_fakes("codex")
        rules = self.home / RULES["codex"]
        rules.parent.mkdir()
        rules.write_text("mine before\n")
        self.install()
        rules.write_text(rules.read_text() + "mine after\n")
        self.install()
        text = rules.read_text()
        self.assertTrue(text.startswith("mine before\n") and text.endswith("mine after\n"), text)
        self.assertEqual(len(self.blocks(RULES["codex"])), 1)
        self.mifal("uninstall")
        self.assertEqual(rules.read_text(), "mine before\nmine after\n")

    def test_an_edited_block_is_kept_by_uninstall_with_a_message(self):
        self.harness_fakes("codex")
        self.install()
        rules = self.home / RULES["codex"]
        rules.write_text(rules.read_text().replace("Matt owns", "Matt, edited, owns", 1))
        edited = rules.read_text()
        result = self.mifal("uninstall")
        self.assertIn("kept the Mifal block in ~/.codex/AGENTS.md: changed since install", result.stdout)
        self.assertEqual(rules.read_text(), edited)

    def test_reinstall_over_an_edited_block_stops_before_any_write_and_keeps_edits_outside_it(self):
        self.harness_fakes("codex", "droid")
        self.install()
        rules = self.home / RULES["codex"]
        rules.write_text("my line outside\n" + rules.read_text())
        self.assertIn("Nothing to change", self.install().stdout)
        self.assertTrue(rules.read_text().startswith("my line outside\n"))
        rules.write_text(rules.read_text().replace("Matt owns", "Matt, edited, owns", 1))
        before = snapshot(self.home)
        result = self.install(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("~/.codex/AGENTS.md: its Mifal block changed since install", result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_overwrite_edits_saves_the_edited_file_then_replaces_the_block(self):
        self.harness_fakes("codex")
        self.install()
        rules = self.home / RULES["codex"]
        rules.write_text(rules.read_text().replace("Matt owns", "Matt, edited, owns", 1))
        edited = rules.read_text()
        result = self.install("--overwrite-edits")
        self.assertRegex(result.stdout, r"save ~/.codex/AGENTS.md -> ~/.agents/mifal-saved/\d{8}T\d{6}Z/.codex/AGENTS.md")
        saved = next((self.home / ".agents/mifal-saved").glob("*/.codex/AGENTS.md"))
        self.assertEqual(saved.read_text(), edited)
        self.assertNotIn("edited", rules.read_text())
        self.assertIn("kept ~/.agents/mifal-saved/", self.mifal("uninstall").stdout)
        self.assertFalse(rules.exists())


class Precedence(Wiring):
    def reads_now(self, name, **env):
        return harness.reads_now(name, self.home, dict({"HOME": str(self.home)}, **env))

    def test_codex_override_skips_codex_and_still_wires_the_others(self):
        self.harness_fakes("codex", "droid")
        (self.home / ".codex").mkdir()
        (self.home / ".codex/AGENTS.override.md").write_text("override\n")
        self.assertEqual(self.reads_now("codex"), self.home / ".codex/AGENTS.override.md")
        result = self.install()
        self.assertIn("skip codex: it reads ~/.codex/AGENTS.override.md", result.stdout)
        self.assertFalse((self.home / ".codex/AGENTS.md").exists())
        self.assertEqual(self.wired(), {"droid"})

    FALLBACK_NOTE = ("~/.claude/CLAUDE.md: OpenCode reads it now, and stops once Mifal writes "
                     "~/.config/opencode/AGENTS.md; copy what you want to keep from it into "
                     "~/.config/opencode/AGENTS.md")

    def fallback(self, text):
        path = self.home / ".claude/CLAUDE.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_opencode_with_only_the_claude_fallback_gets_its_own_file_and_a_note_naming_what_it_stops_reading(self):
        self.harness_fakes("opencode")
        fallback = self.fallback("my claude rules\n")
        self.assertEqual(self.reads_now("opencode"), fallback)
        result = self.install("--harness", "opencode")
        self.assertIn("note " + self.FALLBACK_NOTE, result.stdout)
        self.assertNotIn("skip opencode", result.stdout)
        self.assertEqual(self.wired(), {"opencode"})
        self.assertEqual(fallback.read_text(), "my claude rules\n")
        self.assertEqual(self.reads_now("opencode"), self.home / RULES["opencode"])
        self.mifal("uninstall")
        self.assertFalse((self.home / RULES["opencode"]).exists())
        self.assertEqual(fallback.read_text(), "my claude rules\n")

    def test_the_dry_run_names_the_file_opencode_stops_reading_and_writes_nothing(self):
        self.harness_fakes("opencode")
        self.fallback("my claude rules\n")
        before = snapshot(self.home)
        result = self.install("--harness", "opencode", "--dry-run")
        self.assertIn("note " + self.FALLBACK_NOTE, result.stdout)
        self.assertIn("block ~/.config/opencode/AGENTS.md", result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_no_note_when_the_claude_fallback_holds_nothing_besides_mifals_block(self):
        self.harness_fakes("opencode")
        self.fallback(harness.block("claude", "0.0.0", "a guide\n"))
        result = self.install("--harness", "opencode")
        self.assertNotIn("OpenCode reads it now", result.stdout)
        self.assertEqual(len(self.blocks(RULES["opencode"])), 1)

    def test_a_later_install_that_adds_opencode_stops_on_the_fallback_until_overwrite_edits(self):
        self.harness_fakes("codex", "opencode")
        fallback = self.fallback("my claude rules\n")
        self.install("--harness", "codex")
        before = snapshot(self.home)
        result = self.install("--harness", "opencode", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(self.FALLBACK_NOTE, result.stdout)
        self.assertIn("--overwrite-edits", result.stdout)
        self.assertIn("Nothing was written.", result.stdout)
        self.assertEqual(snapshot(self.home), before)
        result = self.install("--harness", "opencode", "--overwrite-edits")
        self.assertIn("note " + self.FALLBACK_NOTE, result.stdout)
        self.assertEqual(self.wired(), {"codex", "opencode"})
        self.assertEqual(fallback.read_text(), "my claude rules\n")

    def test_the_fallback_stop_says_what_overwrite_edits_accepts_and_neither_moves_nor_saves_the_file(self):
        self.harness_fakes("codex", "opencode")
        self.fallback("my claude rules\n")
        self.install("--harness", "codex")
        result = self.install("--harness", "opencode", check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("For ~/.claude/CLAUDE.md: Mifal leaves it as it is. Run again with --overwrite-edits to "
                      "accept that OpenCode then reads ~/.config/opencode/AGENTS.md instead.", result.stdout)
        self.assertIn("Nothing was written.", result.stdout)
        for wrong in ("Move them aside", "save a copy", "saved", "changed since Mifal wrote them"):
            self.assertNotIn(wrong, result.stdout)

    def test_pi_with_only_claude_md_is_skipped(self):
        self.harness_fakes("pi")
        (self.home / ".pi/agent").mkdir(parents=True)
        (self.home / ".pi/agent/CLAUDE.md").write_text("pi rules\n")
        self.assertEqual(self.reads_now("pi"), self.home / ".pi/agent/CLAUDE.md")
        result = self.install()
        self.assertIn("skip pi: it reads ~/.pi/agent/CLAUDE.md now", result.stdout)
        self.assertFalse((self.home / ".pi/agent/AGENTS.md").exists())

    def test_pi_with_an_override_is_skipped(self):
        self.harness_fakes("pi")
        (self.home / ".pi/agent").mkdir(parents=True)
        (self.home / ".pi/agent/AGENTS.override.md").write_text("pi override\n")
        self.assertEqual(self.reads_now("pi"), self.home / ".pi/agent/AGENTS.override.md")
        self.assertIn("skip pi: it reads ~/.pi/agent/AGENTS.override.md", self.install().stdout)

    def test_a_target_the_user_creates_after_a_skip_gets_only_the_block_and_is_kept_by_uninstall(self):
        self.harness_fakes("pi")
        (self.home / ".pi/agent").mkdir(parents=True)
        (self.home / ".pi/agent/CLAUDE.md").write_text("my pi rules\n")
        self.install("--harness", "pi")
        target = self.home / RULES["pi"]
        target.write_text("kept from my pi rules\n")
        self.assertEqual(self.reads_now("pi"), target)
        self.install("--harness", "pi")
        self.assertEqual(self.wired(), {"pi"})
        self.assertTrue(target.read_text().startswith("kept from my pi rules\n\n<!-- mifal:begin"))
        self.mifal("uninstall")
        self.assertEqual(target.read_text(), "kept from my pi rules\n")

    def test_opencode_reads_its_fallback_as_opencode_does(self):
        self.harness_fakes("opencode")
        (self.home / ".claude").mkdir()
        (self.home / ".claude/CLAUDE.md").write_text("my claude rules\n")
        self.assertEqual(self.reads_now("opencode", OPENCODE_DISABLE_CLAUDE_CODE_PROMPT="1"), None)
        self.install("--harness", "opencode", OPENCODE_DISABLE_CLAUDE_CODE_PROMPT="1")
        self.assertEqual(self.wired(), {"opencode"})

    def test_a_moved_opencode_test_home_moves_the_fallback(self):
        self.harness_fakes("opencode")
        moved = self.home / "elsewhere"
        (moved / ".claude").mkdir(parents=True)
        (moved / ".claude/CLAUDE.md").write_text("rules there\n")
        self.assertEqual(self.reads_now("opencode", OPENCODE_TEST_HOME=str(moved)), moved / ".claude/CLAUDE.md")
        result = self.install("--harness", "opencode", OPENCODE_TEST_HOME=str(moved))
        self.assertIn("note ~/elsewhere/.claude/CLAUDE.md: OpenCode reads it now, and stops once Mifal writes",
                      result.stdout)


class Roots(Wiring):
    def test_each_root_variable_moves_the_wiring_and_the_manifest_records_it(self):
        cases = {
            "claude": ("CLAUDE_CONFIG_DIR", "alt-claude", "CLAUDE.md"),
            "codex": ("CODEX_HOME", "alt-codex", "AGENTS.md"),
            "pi": ("PI_CODING_AGENT_DIR", "alt-pi", "AGENTS.md"),
            "opencode": ("OPENCODE_CONFIG_DIR", "alt-opencode", "AGENTS.md"),
        }
        for name, (variable, folder, rules) in cases.items():
            with self.subTest(harness=name):
                self.setUp()
                self.harness_fakes(name)
                root = self.home / folder
                self.install(**{variable: str(root)})
                self.assertEqual(len(BLOCK.findall((root / rules).read_text())), 1)
                self.assertEqual(self.manifest()["harnesses"][name][0]["root"], os.path.realpath(root))
                self.assertFalse((self.home / RULES[name]).exists())
                if name == "claude":
                    self.assertTrue((root / "skills/tdd").is_symlink())

    def test_xdg_config_home_moves_opencode(self):
        self.harness_fakes("opencode")
        xdg = self.home / "xdg"
        self.install(XDG_CONFIG_HOME=str(xdg))
        self.assertEqual(len(BLOCK.findall((xdg / "opencode/AGENTS.md").read_text())), 1)

    def test_an_empty_xdg_config_home_counts_as_unset(self):
        self.harness_fakes("opencode")
        self.install(XDG_CONFIG_HOME="")
        self.assertEqual(self.wired(), {"opencode"})

    def test_empty_or_relative_opencode_roots_are_refused(self):
        self.harness_fakes("opencode")
        before = snapshot(self.home)
        for variable, value in (("OPENCODE_CONFIG_DIR", ""), ("OPENCODE_CONFIG_DIR", "rel/oc"),
                                ("XDG_CONFIG_HOME", "rel/xdg")):
            with self.subTest(variable=variable, value=value):
                result = self.install(check=False, unchecked=(variable,), **{variable: value})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{variable} is set to {value!r}", result.stdout)
                self.assertEqual(snapshot(self.home), before)
        self.assertFalse((self.root / "rel").exists())

    def test_a_root_outside_home_stops_the_install_unless_allowed(self):
        self.harness_fakes("codex")
        outside = self.root / "outside-codex"
        outside.mkdir()
        (self.home / ".codex").symlink_to(outside)
        before = snapshot(self.home)
        result = self.install(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("~/.codex resolves to", result.stdout)
        self.assertIn("--allow-root-outside-home", result.stdout)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(list(outside.iterdir()), [])
        self.install("--allow-root-outside-home")
        self.assertEqual(len(BLOCK.findall((outside / "AGENTS.md").read_text())), 1)
        self.mifal("uninstall")
        self.assertEqual(list(outside.iterdir()), [])

    def test_a_mifal_folder_outside_home_stops_the_install(self):
        outside = self.root / "outside-skills"
        outside.mkdir()
        (self.home / ".agents").mkdir()
        (self.home / ".agents/skills").symlink_to(outside)
        result = self.install(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("~/.agents/skills resolves to", result.stdout)
        self.assertEqual(list(outside.iterdir()), [])

    def test_a_recorded_folder_that_now_resolves_elsewhere_is_refused(self):
        self.harness_fakes("codex")
        self.install()
        moved = self.home / "moved-codex"
        (self.home / ".codex").rename(moved)
        (self.home / ".codex").symlink_to(moved)
        before = snapshot(self.home)
        result = self.install(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("~/.codex now resolves to ~/moved-codex", result.stdout)
        self.assertEqual(snapshot(self.home), before)
        result = self.mifal("uninstall", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("~/.codex now resolves to ~/moved-codex", result.stdout)
        self.assertEqual(snapshot(self.home), before)


class Selection(Wiring):
    def test_a_home_folder_alone_detects_its_harness(self):
        (self.home / ".factory").mkdir()
        self.install()
        self.assertEqual(self.wired(), {"droid"})

    def test_harness_flag_wires_exactly_the_named_harnesses(self):
        self.harness_fakes("claude", "pi")
        self.install("--harness", "codex", "--harness", "pi")
        self.assertEqual(self.wired(), {"codex", "pi"})

    def test_an_unknown_harness_name_is_refused(self):
        result = self.install("--harness", "vim", check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_a_shell_alias_or_a_dangling_link_is_not_a_harness(self):
        (self.fakebin / "codex").symlink_to(self.root / "nowhere")
        self.install()
        self.assertEqual(self.wired(), set())


class Limits(Wiring):
    def test_a_codex_file_that_would_pass_32_kib_warns(self):
        self.harness_fakes("codex")
        (self.home / ".codex").mkdir()
        (self.home / ".codex/AGENTS.md").write_text("x" * 32000 + "\n")
        self.assertIn("32 KiB", self.install().stdout)

    def test_the_claude_block_is_never_inside_a_fence(self):
        self.harness_fakes("claude")
        rules = self.home / RULES["claude"]
        rules.parent.mkdir()
        rules.write_text("```\nopen fence\n")
        result = self.install()
        self.assertIn("skip claude: ~/.claude/CLAUDE.md ends inside an open code fence", result.stdout)
        self.assertEqual(rules.read_text(), "```\nopen fence\n")
        rules.write_text("```\nclosed\n```\n")
        self.install()
        lines = rules.read_text().splitlines()
        fenced = False
        for line in lines:
            if line.startswith("```"):
                fenced = not fenced
            if line == IMPORT:
                self.assertFalse(fenced)
        self.assertIn(IMPORT, lines)

    def test_a_wired_claude_skipped_on_reinstall_keeps_its_block_and_its_skill_links(self):
        self.harness_fakes("claude")
        self.install()
        rules = self.home / RULES["claude"]
        rules.write_text(rules.read_text() + "```\nopen fence\n")
        links = sorted((self.home / ".claude/skills").iterdir())
        result = self.install()
        self.assertIn("skip claude:", result.stdout)
        self.assertEqual(sorted((self.home / ".claude/skills").iterdir()), links)
        self.assertEqual(len(self.blocks(RULES["claude"])), 1)
        self.mifal("uninstall")
        self.assertFalse((self.home / ".claude/skills").exists())


class FirstInstallOutput(Wiring):
    def test_a_first_install_prints_a_short_summary_with_every_rules_file_and_the_next_step(self):
        self.harness_fakes(*RULES)
        preview = self.install("--dry-run")
        result = self.install()
        lines = result.stdout.splitlines()
        self.assertLess(len(lines), 30, result.stdout)
        self.assertGreater(len(preview.stdout.splitlines()), 300)
        for rel in RULES.values():
            self.assertIn(f"block ~/{rel}", lines)
        self.assertIn("~/.agents/skills: 39 skills", result.stdout)
        self.assertIn("~/.claude/skills: 39 links", result.stdout)
        self.assertIn("Wired: Claude Code, Codex, Droid, Pi, OpenCode", result.stdout)
        self.assertIn("Next: run `mifal doctor`", result.stdout)

    def test_a_first_install_still_names_what_it_moves_aside(self):
        self.harness_fakes("claude")
        (self.home / ".claude/skills/tdd").mkdir(parents=True)
        (self.home / ".claude/skills/tdd/SKILL.md").write_text("mine\n")
        result = self.install()
        self.assertRegex(result.stdout, r"(?m)^backup ~/.claude/skills/tdd -> ")


class Guide(Wiring):
    def test_the_guide_is_generic_and_names_only_installed_paths(self):
        self.install()
        text = self.guide()
        self.assertEqual([line for line in text.splitlines() if denied("AGENTS.md", line)], [])
        for path in set(re.findall(r"~/(\.agents/[\w./-]+)", text)):
            with self.subTest(path=path):
                self.assertTrue((self.home / path.rstrip(".")).exists(), path)
        self.assertIn("Matt owns engineering in every harness.", text)


if __name__ == "__main__":
    unittest.main()
