import os
import io
import json
import re
import sys
import subprocess
import unittest
from unittest.mock import patch
from pathlib import Path

from support import PYTHON, REPO, Sandbox, changed, snapshot
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
    def test_a_rules_file_that_would_pass_32_kib_with_the_block_stops_the_run_with_nothing_written(self):
        for name in ("codex", "claude"):
            with self.subTest(harness=name):
                self.setUp()
                self.harness_fakes(name)
                rules = self.home / RULES[name]
                rules.parent.mkdir()
                rules.write_text("x" * 32700 + "\n")
                before = snapshot(self.home)
                result = self.install(check=False)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                lines = result.stdout.splitlines()
                self.assertTrue(any(l.startswith(f"~/{RULES[name]} would be ") and l.endswith(
                    " bytes with Mifal's block, past the 32 KiB (32768 bytes) that Codex reads. Shorten it, then "
                    "run again.") for l in lines), result.stdout)
                self.assertIn("Nothing was written.", lines)
                self.assertEqual(snapshot(self.home), before)

    def test_a_rules_file_at_nine_tenths_of_32_kib_installs_and_prints_the_near_limit_warning(self):
        for name, mine in (("codex", 22000), ("claude", 30000)):
            with self.subTest(harness=name):
                self.setUp()
                self.harness_fakes(name)
                rules = self.home / RULES[name]
                rules.parent.mkdir()
                rules.write_text("x" * mine + "\n")
                result = self.install()
                size = len(rules.read_bytes())
                self.assertTrue(29492 <= size <= 32768, size)
                self.assertEqual(len(self.blocks(RULES[name])), 1)
                self.assertIn(f"warn {name}: ~/{RULES[name]} would be {size} bytes, near Codex's 32 KiB default cap",
                              result.stdout.splitlines())

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


class SkillFilters(Wiring):
    def test_non_json_numbers_and_deep_settings_are_unknown_without_disclosure(self):
        for name in ('claude', 'droid', 'pi', 'opencode'):
            filename = 'opencode.json' if name == 'opencode' else 'settings.json'
            for text in ('{"unrelated":NaN}', '{"unrelated":' + '[' * 10000 + '0' + ']' * 10000 + '}'):
                result = self.other_audit(name, text, filename)
                self.assertIn('exclusions unknown', repr(result.warnings))
                self.assertNotIn('NaN', repr(result))

    def other_audit(self, name, text, filename='settings.json'):
        root = self.home / '.config/opencode' if name == 'opencode' else self.home / ('other-' + name)
        root.mkdir(parents=True, exist_ok=True)
        (root / filename).write_text(text)
        return harness.skill_filters(name, self.home, root, self.home / '.agents/skills', {'tdd', 'team-lead'})

    def test_claude_modes_and_droid_normalized_names_hide_only_known_skills(self):
        for mode, hidden in [('on', False), ('name-only', False), ('user-invocable-only', True), ('off', True)]:
            result = self.other_audit('claude', json.dumps({'skillOverrides': {'tdd': mode, 'sk-secret': 'off'}}))
            self.assertEqual(any('tdd: configured exclusion detected' in detail for detail, _ in result.warnings), hidden)
            self.assertNotIn('sk-secret', repr(result))
        result = self.other_audit('droid', '{"disabledSkills":["--TDD--","TEAM LEAD","sk-secret"]}')
        self.assertEqual(len(result.warnings), 2)
        self.assertNotIn('sk-secret', repr(result))
        for name, text in [('claude', '{"skillOverrides":[]}'), ('droid', '{"disabledSkills":[false]}')]:
            self.assertIn('exclusions unknown', repr(self.other_audit(name, text)))

    def test_pi_pool_patterns_and_ignore_pruning_follow_the_source_order(self):
        pool = self.home / '.agents/skills'
        (pool / 'tdd').mkdir(parents=True)
        (pool / 'tdd/SKILL.md').write_text('a skill')
        for patterns, hidden in [(['!tdd'], True), (['!tdd', '+skills/tdd'], False),
                                 (['-skills/tdd', '+skills/tdd', '!tdd'], True),
                                 (['!TDD'], False), (['!t[d]d'], True), (['plain/resource'], False),
                                 (['!~/.agents/skills/tdd/../tdd/SKILL.md'], True)]:
            result = self.other_audit('pi', json.dumps({'skills': patterns}))
            self.assertEqual(any('tdd: configured exclusion detected' in detail for detail, _ in result.warnings), hidden)
        for rules, hidden in [('TDD/\n!tdd/SKILL.md\n', True), ('tdd/\n!tdd/\n', False),
                              ('tdd/SKILL.md\n', True), ('/other/tdd\n', False)]:
            (pool / '.gitignore').write_text(rules)
            result = self.other_audit('pi', '{"skills":[]}')
            self.assertEqual(any('tdd: configured exclusion detected' in detail for detail, _ in result.warnings), hidden)
        (pool / '.gitignore').unlink()
        result = self.other_audit('pi', '{"skills":["!{tdd,team-lead}"]}')
        self.assertIn('exclusions unknown', repr(result))
        self.assertNotIn('no exclusion found', result.coverage)
        encoded = 'file://' + str(pool / 'tdd/SKILL.md').replace('/skills/', '/skills%2F')
        result = self.other_audit('pi', json.dumps({'skills': ['!' + encoded]}))
        self.assertIn('exclusions unknown', repr(result.warnings))
        self.assertNotIn('configured exclusion detected', repr(result.warnings))

    def test_opencode_jsonc_and_merged_permission_maps_preserve_order(self):
        result = self.other_audit('opencode', '// comment\n{"url":"https://secret.invalid/*",'
                                  '"permission":{"skill":{"tdd":"allow","*":"deny",},},}', 'config.json')
        self.assertEqual(len(result.warnings), 2)
        result = self.other_audit('opencode', '{"permission":{"skill":{"tdd":"allow"}}}', 'opencode.json')
        self.assertEqual(len(result.warnings), 2)
        self.assertTrue(all('config.json at permission.skill' in detail for detail, _ in result.warnings))
        result = self.other_audit('opencode', '{"permission":{"skill":{"*":"ask"}}}', 'opencode.jsonc')
        self.assertEqual(result.warnings, [])
        root = self.home / '.config/opencode'
        for file in ('config.json', 'opencode.json', 'opencode.jsonc'):
            (root / file).unlink()
        result = self.other_audit('opencode', '{"permission":{"skill":{"tdd *":"deny"}}}', 'opencode.json')
        self.assertEqual(len(result.warnings), 1)
        self.assertIn('tdd: configured exclusion detected', result.warnings[0][0])
        result = self.other_audit('opencode', '{"permission":"deny"}', 'opencode.json')
        self.assertEqual(len(result.warnings), 2)
        result = self.other_audit('opencode', '{"permission":{"skill":{"tdd":"{file:/secret}"}}}', 'opencode.json')
        self.assertIn('exclusions unknown', repr(result))
        self.assertNotIn('/secret', repr(result))

    def test_opencode_override_ignores_legacy_global_filename(self):
        root = self.home / 'custom-opencode'
        root.mkdir()
        (root / 'config.json').write_text('{"permission":"deny"}')
        result = harness.skill_filters('opencode', self.home, root, self.home / '.agents/skills', {'tdd'})
        self.assertEqual(result.warnings, [])
        self.assertNotIn(str(root / 'config.json'), result.coverage)
        (root / 'opencode.jsonc').write_text('{"permission":{"skill":"deny"}}')
        result = harness.skill_filters('opencode', self.home, root, self.home / '.agents/skills', {'tdd'})
        self.assertIn('tdd: configured exclusion detected', repr(result.warnings))
        global_root = self.home / 'xdg/opencode'
        global_root.mkdir(parents=True)
        (global_root / 'config.json').write_text('{"permission":"deny"}')
        result = harness.skill_filters('opencode', self.home, global_root, self.home / '.agents/skills', {'tdd'},
                                       env={'XDG_CONFIG_HOME': str(global_root.parent)})
        self.assertIn('config.json at permission.*', repr(result.warnings))

    def audit(self, text=None, root=None, name="codex"):
        read = getattr(harness, "skill_filters", None)
        self.assertTrue(callable(read), "Harness facts must expose the skill-filter audit")
        root = root or self.home / ".codex"
        root.mkdir(exist_ok=True)
        if text is not None:
            (root / "config.toml").write_text(text)
        return read(name, self.home, root, self.home / ".agents/skills", {"tdd", "team-lead"})

    def test_codex_original_link_swap_reads_only_the_resolved_settings(self):
        root = self.home / '.codex'
        root.mkdir()
        config = root / 'config.toml'
        target = self.home / 'public.toml'
        target.write_text('[[skills.config]]\nname = "tdd"\nenabled = false\n')
        credential = self.home / 'auth.json'
        credential.write_text('secret = "must-not-read"\n')
        config.symlink_to(target)
        opens = []
        io_open, os_open = io.open, os.open

        def swapped(opening, path, *args, **kwargs):
            if not isinstance(path, int) and Path(path) in (config, target):
                opens.append(Path(path))
                if len(opens) == 1:
                    config.unlink()
                    config.symlink_to(credential)
            return opening(path, *args, **kwargs)

        with patch('io.open', side_effect=lambda p, *a, **k: swapped(io_open, p, *a, **k)), \
                patch('os.open', side_effect=lambda p, *a, **k: swapped(os_open, p, *a, **k)):
            result = self.audit()
        self.assertIn('tdd: configured exclusion detected', repr(result.warnings))
        self.assertEqual(opens, [target])
        self.assertNotIn('must-not-read', repr(result))

    def test_codex_selectors_match_case_aliases_by_file_identity(self):
        document = self.home / '.agents/skills/tdd/SKILL.md'
        document.parent.mkdir(parents=True)
        document.write_text('a skill')
        for relative in ('.agents/skills/TDD/SKILL.md', '.agents/skills/tdd/skill.md',
                         '.AGENTS/skills/tdd/SKILL.md'):
            with self.subTest(path=relative):
                alias = self.home / relative
                if not alias.exists():
                    alias.parent.mkdir(parents=True, exist_ok=True)
                    os.link(document, alias)
                result = self.audit('[[skills.config]]\npath = "' + str(alias) + '"\nenabled = false\n')
                self.assertIn('tdd: configured exclusion detected', repr(result.warnings))
        document.unlink()
        result = self.audit('[[skills.config]]\npath = "' + str(document) + '"\nenabled = false\n')
        self.assertIn('tdd: configured exclusion detected', repr(result.warnings))

    def test_codex_link_loop_uppercase_and_settings_names_have_fitting_diagnostics(self):
        root = self.home / '.codex'
        root.mkdir()
        config = root / 'config.toml'
        config.symlink_to(config)
        result = self.audit()
        self.assertIn('link loop', repr(result.warnings))
        self.assertNotIn('restore read access', repr(result.warnings))
        config.unlink()
        target = self.home / 'settings.TOML'
        target.write_text('[[skills.config]]\nname = "tdd"\nenabled = false\n')
        config.symlink_to(target)
        self.assertIn('tdd: configured exclusion detected', repr(self.audit().warnings))
        for name in ('settings.json', 'opencode.json'):
            config.unlink()
            target = self.home / name
            target.write_text('{}')
            config.symlink_to(target)
            result = self.audit()
            self.assertIn('regular TOML file', repr(result.warnings))
            self.assertNotIn('credential', repr(result.warnings))

    def test_codex_fifo_swap_finishes_as_unknown_within_three_seconds(self):
        code = '''
import io, os, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from mifal import harness
home = Path(sys.argv[2]); root = home / '.codex'; root.mkdir()
target = root / 'config.toml'; target.write_text('')
io_open, os_open = io.open, os.open
swapped = False
def opening(original, path, *args, **kwargs):
    global swapped
    if not isinstance(path, int) and Path(path) == target and not swapped:
        swapped = True; target.unlink(); os.mkfifo(target)
    return original(path, *args, **kwargs)
with patch('io.open', side_effect=lambda p, *a, **k: opening(io_open, p, *a, **k)), patch('os.open', side_effect=lambda p, *a, **k: opening(os_open, p, *a, **k)):
    result = harness.skill_filters('codex', home, root, home / '.agents/skills', {'tdd'})
assert result.unreadable and 'regular TOML file' in repr(result.warnings), repr(result)
'''
        result = subprocess.run([PYTHON, '-B', '-c', code, str(REPO / 'lib'), str(self.home)],
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_codex_setting_file_and_0166_schema_belong_to_each_recorded_root(self):
        moved = self.home / "codex-work"
        result = self.audit(root=moved)
        self.assertIn(str(moved / "config.toml"), result.coverage)
        self.assertIn("supports Codex 0.166.0 [[skills.config]] (path or name, enabled)", result.coverage)
        self.assertIn("no exclusion found", result.coverage)
        self.assertIn("Codex version and session -c overrides: unknown", result.coverage)
        self.assertEqual(result.warnings, [])

    def test_codex_path_selects_the_skill_document_and_later_name_reenables_it(self):
        document = self.home / ".agents/skills/tdd/SKILL.md"
        document.parent.mkdir(parents=True)
        document.write_text("a skill")
        for path in (str(document), "../.agents/skills/tdd/SKILL.md", "~/.agents/skills/tdd/SKILL.md"):
            with self.subTest(path=path):
                text = '[[skills.config]]\npath = "' + path + '"\nenabled = false\n'
                result = self.audit(text)
                self.assertIn("tdd: configured exclusion detected", result.warnings[0][0])
                self.assertIn("enabled = true", result.warnings[0][1])
                self.assertEqual(self.audit(text + '[[skills.config]]\nname = "tdd"\nenabled = true\n').warnings, [])
        folder = str(document.parent)
        self.assertEqual(self.audit('[[skills.config]]\npath = "' + folder + '"\nenabled = false\n').warnings, [])

    def test_codex_0166_skills_config_rs_205_212_skips_selector_mistakes_only(self):
        for selector in ('name = " "', 'name = "team-lead"\npath = "/other/SKILL.md"', ''):
            with self.subTest(selector=selector):
                result = self.audit('[[skills.config]]\nname = " tdd "\nenabled = false\n'
                                    '[[skills.config]]\n' + selector + '\nenabled = false\n')
                self.assertEqual(len(result.warnings), 1)
                self.assertIn("tdd: configured exclusion detected", result.warnings[0][0])
                self.assertIn("skipped", result.notes[0])

    def test_codex_enabled_is_required_boolean_and_selectors_are_strings(self):
        for entry in ('name = "tdd"', 'name = "tdd"\nenabled = "false"',
                      'path = 1\nenabled = false', 'name = 1\nenabled = false'):
            with self.subTest(entry=entry):
                result = self.audit('[[skills.config]]\n' + entry)
                self.assertIn("invalid skills.config", result.warnings[0][0])
                self.assertIn("boolean enabled", result.warnings[0][1])

    def test_codex_nul_path_is_unmatchable_without_discarding_other_rules(self):
        result = self.audit('[[skills.config]]\npath = "\\u0000"\nenabled = false\n'
                            '[[skills.config]]\nname = "tdd"\nenabled = false\n')
        self.assertEqual(len(result.warnings), 1)
        self.assertIn('tdd: configured exclusion detected', result.warnings[0][0])

    def test_codex_linked_config_is_read_without_exposing_other_values(self):
        read = getattr(harness, "skill_filters", None)
        self.assertTrue(callable(read), "Harness facts must expose the skill-filter audit")
        root = self.home / ".codex"
        root.mkdir()
        target = self.home / "dotfiles.toml"
        target.write_text('model = "secret-placeholder"\n[[skills.config]]\nname = "tdd"\nenabled = false\n')
        (root / "config.toml").symlink_to(target)
        result = self.audit()
        self.assertIn("tdd: configured exclusion detected", result.warnings[0][0])
        self.assertNotIn("secret-placeholder", repr(result))

    def test_codex_read_denial_reports_unknown_without_a_mode_bit_precheck(self):
        self.audit('')
        config = self.home / ".codex/config.toml"
        config.chmod(0)
        self.addCleanup(config.chmod, 0o600)
        result = self.audit()
        self.assertTrue(result.unreadable)
        self.assertIn("cannot be read; exclusions unknown", result.warnings[0][0])
        self.assertIn("restore read access", result.warnings[0][1])

    def test_codex_home_and_dotfiles_folder_names_never_identify_credentials(self):
        for folder in ('auth', 'token'):
            with self.subTest(folder=folder):
                root = self.home / folder / '.codex'
                root.mkdir(parents=True)
                target = self.home / 'dotfiles' / folder / 'settings.toml'
                target.parent.mkdir(parents=True)
                (root / 'config.toml').symlink_to(target)
                for text, count in (('', 0), ('[[skills.config]]\nname = "tdd"\nenabled = false\n', 1)):
                    target.write_text(text)
                    result = self.audit(root=root)
                    self.assertEqual(len(result.warnings), count)
                    self.assertNotIn('credential', repr(result))
                    if count:
                        self.assertIn('tdd: configured exclusion detected', result.warnings[0][0])

    def test_codex_nonregular_config_needs_regular_toml_not_read_access(self):
        for kind in ('fifo', 'directory', 'device'):
            with self.subTest(kind=kind):
                root = self.home / kind
                root.mkdir()
                config = root / 'config.toml'
                if kind == 'fifo':
                    os.mkfifo(config)
                elif kind == 'directory':
                    config.mkdir()
                else:
                    config.symlink_to(os.devnull)
                result = self.audit(root=root)
                self.assertTrue(result.unreadable)
                self.assertIn('exclusions unknown', result.warnings[0][0])
                self.assertIn('regular TOML file', result.warnings[0][1])
                self.assertNotIn('restore read access', result.warnings[0][1])

    def test_codex_nonregular_target_names_are_never_credential_file_names(self):
        for kind in ('directory', 'fifo'):
            for filename in ('auth', 'token'):
                with self.subTest(kind=kind, name=filename):
                    root = self.home / (kind + '-' + filename)
                    root.mkdir()
                    target = self.home / (kind + '-targets') / filename
                    target.parent.mkdir(exist_ok=True)
                    if kind == 'directory':
                        target.mkdir()
                    else:
                        os.mkfifo(target)
                    (root / 'config.toml').symlink_to(target)
                    result = self.audit(root=root)
                    self.assertTrue(result.unreadable)
                    self.assertEqual(len(result.warnings), 1)
                    self.assertNotIn('credential', result.warnings[0][0])
                    self.assertIn('regular TOML file', result.warnings[0][1])

    def test_claude_blank_settings_are_an_empty_object(self):
        root = self.home / '.claude'
        root.mkdir()
        for text in (' \n\t', '\ufeff \n\t'):
            (root / 'settings.json').write_text(text)
            result = self.audit(name='claude', root=root)
            self.assertIsNotNone(result)
            self.assertEqual(result.warnings, [])

    def test_droid_jsonc_comments_hide_known_skills_without_accepting_trailing_commas(self):
        root = self.home / '.factory'
        root.mkdir()
        config = root / 'settings.json'
        for text, hidden, unknown in (
                ('{/* plain comment */"unrelated":"https://secret/"}', False, False),
                ('{// comment\n"disabledSkills":["TDD"]}', True, False),
                ('{"disabledSkills":["TDD",]}', False, True)):
            config.write_text(text)
            result = self.audit(name='droid', root=root)
            self.assertEqual(any('configured exclusion detected' in detail for detail, fix in result.warnings), hidden)
            self.assertEqual(any('unknown' in detail for detail, fix in result.warnings), unknown)
            self.assertNotIn('https://secret/', repr(result))

    def test_other_harnesses_do_not_audit_codex_settings(self):
        for name in ("claude", "droid", "pi", "opencode"):
            with self.subTest(name=name):
                result = self.audit('[[skills.config]]\nname = "tdd"\nenabled = false\n', name=name)
                self.assertEqual(result.warnings, [])
                self.assertNotIn('Codex 0.166.0', result.coverage)


if __name__ == "__main__":
    unittest.main()
