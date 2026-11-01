import json
import os
import re
import shutil
import unittest

import test_update
from support import PYTHON, REPO, Sandbox, snapshot

HERDR_STATUS = json.dumps({"client": {"version": "0.9.5"}, "server": {"running": True, "version": "0.9.5"}})
SCHEMA = REPO / "tools/herdr_adapter/api-schema.json"
HARNESSES = ("claude", "codex", "droid", "pi", "opencode")
RULES = {"claude": ".claude/CLAUDE.md", "codex": ".codex/AGENTS.md", "droid": ".factory/AGENTS.md",
         "pi": ".pi/agent/AGENTS.md", "opencode": ".config/opencode/AGENTS.md"}
NETWORK = ("curl", "wget", "git", "nc", "ssh")
# Credential, token and auth files; settings have a separate declared allowance.
PRIVATE = (".claude/.credentials.json", ".codex/auth.json", ".factory/auth.json", ".factory/credentials.json",
           ".pi/agent/auth.json", ".pi/agent/oauth.json", ".config/opencode/auth.json",
           ".local/share/opencode/auth.json", ".config/herdr/token")


class Doctor(Sandbox):
    def setUp(self):
        super().setUp()
        self.herdr_schema(SCHEMA.read_text())
        self.harness_fakes(*HARNESSES)
        self.fake("agent-browser", "exit 0")
        self.install()

    def herdr_schema(self, text):
        """A fake Herdr 0.9.5 whose `herdr api schema --json` prints text."""
        schema = self.root / "herdr-schema.json"
        schema.write_text(text)
        self.fake("herdr", 'case "$1" in --version) echo "herdr 0.9.5";; status) echo \'%s\';; '
                           'api) [ "$2 $3" = "schema --json" ] && cat "%s";; esac' % (HERDR_STATUS, schema))

    def doctor(self, **kw):
        return self.mifal("doctor", check=False, **kw)

    def failed(self, result):
        return [line for line in result.stdout.splitlines() if line.startswith("FAIL")]

    def assert_fails_with_fix(self, result, check):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        lines = result.stdout.splitlines()
        at = next((i for i, line in enumerate(lines) if line.startswith("FAIL") and check in line), None)
        self.assertIsNotNone(at, result.stdout)
        self.assertTrue(lines[at + 1].strip().startswith("fix: "), result.stdout)


class Healthy(Doctor):
    def test_green_on_a_fresh_install(self):
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.failed(result), [])
        for name in HARNESSES:
            self.assertRegex(result.stdout, rf"(?m)^PASS guide {name}\b")
        self.assertRegex(result.stdout, r"(?m)^PASS herdr: 0\.9\.5, server 0\.9\.5")
        self.assertRegex(result.stdout, r"(?m)^PASS herdr protocol: 22, the schema the team lead's adapter speaks")
        self.assertRegex(result.stdout, r"(?m)^PASS agent-browser: ")
        self.assertEqual([c for c in self.called() if c.startswith("agent-browser")], [])

    def test_green_after_the_clone_is_deleted(self):
        shutil.rmtree(self.clone)
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class Agents(Doctor):
    def test_no_agent_is_said_to_read_the_pool_natively(self):
        result = self.doctor()
        self.assertNotIn("natively", result.stdout)
        self.assertNotRegex(result.stdout, r"(?m)^PASS skills (codex|droid|pi|opencode)")

    def test_each_served_agent_names_the_file_that_holds_its_block(self):
        result = self.doctor()
        for name, rel in RULES.items():
            with self.subTest(agent=name):
                self.assertRegex(result.stdout, rf"(?m)^PASS guide {name}: block in ~/{re.escape(rel)}$")

    def test_no_note_about_saved_copies_when_none_were_saved(self):
        self.assertNotIn("saved in", self.doctor().stdout)


class Elsewhere(Sandbox):
    def setUp(self):
        super().setUp()
        self.fake("agent-browser", "exit 0")

    def doctor(self, **kw):
        return self.mifal("doctor", check=False, **kw)

    def test_a_detected_agent_the_install_never_recorded_is_listed_as_not_served(self):
        self.harness_fakes("codex")
        self.install()
        self.harness_fakes("droid")
        result = self.doctor()
        self.assertRegex(result.stdout,
                         r"(?m)^note found droid at ~/\.factory, not served; run \./install\.sh to add it$")
        self.assertNotIn("found codex", result.stdout)

    def test_a_recorded_skip_that_no_longer_holds_is_not_served_and_the_fix_wires_it(self):
        self.harness_fakes("claude", "opencode")
        (self.home / ".claude").mkdir()
        (self.home / ".claude/CLAUDE.md").write_text("my claude rules\n")
        self.install("--harness", "claude")
        data = self.manifest()
        root = str((self.home / ".config").resolve() / "opencode")
        data["harnesses"]["opencode"] = {"root": root, "rules": root + "/AGENTS.md", "status": "skipped"}
        (self.home / ".agents/mifal/install-manifest.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        result = self.doctor()
        self.assertRegex(result.stdout, r"(?m)^WARN guide opencode: found at ~/\.config/opencode, not served$")
        fix = re.search(r"(?m)^     fix: (.+)$", result.stdout.split("WARN guide opencode", 1)[1]).group(1)
        self.assertIn(" --overwrite-edits in your Mifal clone", fix)
        self.assertIn("OpenCode then reads ~/.config/opencode/AGENTS.md, not ~/.claude/CLAUDE.md", fix)
        self.assertTrue(fix.startswith(f"run ./install.sh --home opencode={root} --overwrite-edits in your Mifal "
                                       "clone; "), fix)
        self.assertNotIn("OPENCODE_CONFIG_DIR=", fix)
        self.assertNotIn("not wired yet", result.stdout)
        self.install("--overwrite-edits")
        self.assertEqual(self.manifest()["harnesses"]["opencode"][0]["status"], "skipped")
        self.assertFalse(os.path.lexists(root))
        self.install("--home", f"opencode={root}", "--overwrite-edits")
        self.assertEqual(self.manifest()["harnesses"]["opencode"][0]["status"], "wired")
        self.assertRegex(self.doctor().stdout, r"(?m)^PASS guide opencode: block in ~/\.config/opencode/AGENTS\.md$")

    def test_the_not_served_fix_for_a_custom_recorded_root_sets_the_variable_to_reach_it(self):
        self.harness_fakes("claude", "opencode")
        (self.home / ".claude").mkdir()
        (self.home / ".claude/CLAUDE.md").write_text("my claude rules\n")
        self.install("--harness", "claude")
        data = self.manifest()
        root = str((self.home / "alt-opencode").resolve())
        data["harnesses"]["opencode"] = {"root": root, "rules": root + "/AGENTS.md", "status": "skipped"}
        (self.home / ".agents/mifal/install-manifest.json").write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n")
        result = self.doctor()
        self.assertRegex(result.stdout, r"(?m)^WARN guide opencode: found at ~/alt-opencode, not served$")
        fix = re.search(r"(?m)^     fix: (.+)$", result.stdout.split("WARN guide opencode", 1)[1]).group(1)
        self.assertTrue(fix.startswith(
            "run ./install.sh --home opencode=" + root + " --overwrite-edits in your Mifal clone; "), fix)
        self.assertIn("OpenCode then reads ~/alt-opencode/AGENTS.md, not ~/.claude/CLAUDE.md", fix)

    def test_a_detected_agent_is_listed_when_the_install_served_none(self):
        self.install()
        self.assertEqual(self.manifest()["harnesses"], {})
        self.harness_fakes("codex")
        self.assertRegex(self.doctor().stdout,
                         r"(?m)^note found codex at ~/\.codex, not served; run \./install\.sh to add it$")

    def test_an_agent_the_install_skipped_is_explained_once_by_its_own_line(self):
        override = self.home / ".codex/AGENTS.override.md"
        override.parent.mkdir()
        override.write_text("override\n")
        self.harness_fakes("codex")
        self.install()
        result = self.doctor()
        self.assertRegex(result.stdout, r"(?m)^FAIL guide codex: ")
        self.assertNotIn("found codex", result.stdout)

    def test_a_relative_xdg_config_home_warns_instead_of_stopping_the_doctor(self):
        self.harness_fakes("codex")
        self.install()
        result = self.doctor(unchecked=("XDG_CONFIG_HOME",), XDG_CONFIG_HOME="rel/xdg")
        self.assertRegex(result.stdout,
                         r"(?m)^WARN agents: cannot look for agents or Claude homes Mifal does not serve: ")
        self.assertNotIn("Traceback", result.stderr)
        self.assertRegex(result.stdout, r"(?m)^doctor: ")


class Broken(Doctor):
    def test_a_deleted_opencode_rules_file_fails_with_its_fix(self):
        (self.home / RULES["opencode"]).unlink()
        self.assert_fails_with_fix(self.doctor(), "guide opencode")

    def test_a_deleted_skill_fails_with_its_fix(self):
        shutil.rmtree(self.home / ".agents/skills/tdd")
        self.assert_fails_with_fix(self.doctor(), "manifest")

    def test_an_edited_block_fails_with_its_fix(self):
        rules = self.home / ".codex/AGENTS.md"
        rules.write_text(rules.read_text().replace("Matt owns", "Matt, edited, owns", 1))
        self.assert_fails_with_fix(self.doctor(), "guide codex")

    def test_missing_herdr_fails_with_its_fix(self):
        self.unfake("herdr")
        self.assert_fails_with_fix(self.doctor(), "herdr")

    def test_a_herdr_with_another_protocol_warns_that_only_the_experimental_adapter_refuses_it(self):
        schema = json.loads(SCHEMA.read_text())
        self.herdr_schema(json.dumps(dict(schema, protocol=23)))
        result = self.doctor()
        self.assertEqual(self.failed(result), [], result.stdout)
        self.assertRegex(result.stdout, r"(?m)^WARN herdr protocol: Herdr speaks protocol 23, the team lead's "
                                        r"experimental adapter speaks protocol 22")

    def test_a_herdr_schema_that_changed_within_the_protocol_warns(self):
        schema = json.loads(SCHEMA.read_text())
        self.herdr_schema(json.dumps(dict(schema, schemas=dict(schema["schemas"], extra={"type": "object"}))))
        result = self.doctor()
        self.assertEqual(self.failed(result), [], result.stdout)
        self.assertRegex(result.stdout, r"(?m)^WARN herdr protocol: 22, but its schema differs")

    def test_a_missing_agent_browser_cli_warns_with_its_install_command(self):
        self.unfake("agent-browser")
        result = self.doctor()
        self.assertEqual(self.failed(result), [], result.stdout)
        self.assertRegex(result.stdout, r"(?m)^WARN agent-browser: .*not on PATH")
        self.assertIn("npm i -g agent-browser && agent-browser install", result.stdout)

    def test_a_herdr_that_prints_no_schema_warns(self):
        for printed in ("", "[22]", "null"):
            with self.subTest(printed=printed):
                self.herdr_schema(printed)
                result = self.doctor()
                self.assertRegex(result.stdout, r"(?m)^WARN herdr protocol: could not compare")

    def test_a_changed_ask_matt_body_fails_with_its_fix(self):
        body = self.home / ".agents/skills/ask-matt/SKILL.md"
        body.write_text(body.read_text() + "\nA local change.\n")
        self.assert_fails_with_fix(self.doctor(), "ask-matt pin")

    def test_a_missing_claude_skill_link_fails_with_its_fix(self):
        (self.home / ".claude/skills/tdd").unlink()
        self.assert_fails_with_fix(self.doctor(), "skills claude")

    def test_a_skill_of_the_users_own_in_the_pool_warns_with_its_fix_and_does_not_fail(self):
        own = self.home / ".agents/skills/my-own-skill"
        own.mkdir()
        (own / "SKILL.md").write_text("mine\n")
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.failed(result), [])
        lines = result.stdout.splitlines()
        at = next((i for i, line in enumerate(lines) if line.startswith("WARN your skills claude")), None)
        self.assertIsNotNone(at, result.stdout)
        self.assertIn("my-own-skill", lines[at])
        self.assertIn("ln -s", lines[at + 1])
        (self.home / ".claude/skills/my-own-skill").symlink_to(own)
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("your skills claude", result.stdout)

    def own_skill(self):
        own = self.home / ".agents/skills/my-own-skill"
        own.mkdir()
        (own / "SKILL.md").write_text("mine\n")
        return own

    def test_a_relative_link_to_a_skill_of_the_users_own_counts_as_linked(self):
        self.own_skill()
        (self.home / ".claude/skills/my-own-skill").symlink_to("../../.agents/skills/my-own-skill")
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("your skills claude", result.stdout)

    def test_a_link_to_a_skill_of_the_users_own_through_a_linked_pool_path_counts_as_linked(self):
        self.own_skill()
        (self.root / "alias").symlink_to(self.home / ".agents/skills")
        (self.home / ".claude/skills/my-own-skill").symlink_to(self.root / "alias/my-own-skill")
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("your skills claude", result.stdout)

    def test_a_link_that_resolves_elsewhere_still_warns_about_a_skill_of_the_users_own(self):
        self.own_skill()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (self.home / ".claude/skills/my-own-skill").symlink_to(elsewhere)
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertRegex(result.stdout, r"(?m)^WARN your skills claude.*my-own-skill")

    def test_a_relative_link_to_a_mifal_skill_still_fails_because_uninstall_matches_the_recorded_text(self):
        link = self.home / ".claude/skills/tdd"
        link.unlink()
        link.symlink_to("../../.agents/skills/tdd")
        self.assert_fails_with_fix(self.doctor(), "skills claude")

    def test_a_missing_link_for_a_mifal_skill_still_fails_next_to_the_users_own(self):
        own = self.home / ".agents/skills/my-own-skill"
        own.mkdir()
        (own / "SKILL.md").write_text("mine\n")
        (self.home / ".claude/skills/tdd").unlink()
        self.assert_fails_with_fix(self.doctor(), "skills claude")

    def test_a_codex_override_created_after_install_fails_with_its_fix(self):
        (self.home / ".codex/AGENTS.override.md").write_text("override\n")
        self.assert_fails_with_fix(self.doctor(), "guide codex")


class CodexSkillFilters(Doctor):
    def test_plain_homes_with_no_config_or_no_skill_setting_add_no_warning(self):
        for text in (None, '', 'model = "placeholder"\n'):
            with self.subTest(text=text):
                if text is not None:
                    self.config(text)
                result = self.doctor()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotRegex(result.stdout, r'(?m)^WARN skill filters codex:')
                self.assertRegex(result.stdout, r'note skill filters codex:.*no exclusion found.*config.toml')
                self.assertIn('Codex version and session -c overrides: unknown', result.stdout)

    def config(self, text, root=None):
        path = (root or self.home / ".codex") / "config.toml"
        path.write_text(text)
        return path

    def filter_lines(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("supports Codex 0.166.0", result.stdout)
        self.assertIn("Codex version and session -c overrides: unknown", result.stdout)
        return [line for line in result.stdout.splitlines() if "skill filters codex" in line]

    def test_disabled_mifal_document_warns_with_file_key_and_fix(self):
        self.config('[[skills.config]]\npath = "' + str(self.home / '.agents/skills/tdd/SKILL.md') +
                    '"\nenabled = false\n')
        result = self.doctor()
        self.assertIn("tdd: configured exclusion detected", result.stdout)
        lines = self.filter_lines(result)
        self.assertTrue(any("configured exclusion detected" in line and "tdd" in line and
                            "~/.codex/config.toml" in line and "skills.config" in line for line in lines),
                        result.stdout)
        self.assertRegex(result.stdout, r"configured exclusion detected[^\n]*\n     fix: .*enabled = true")

    def test_name_selector_and_later_path_rule_follow_codex_order(self):
        document = str(self.home / '.agents/skills/tdd/SKILL.md')
        self.config('[[skills.config]]\nname = "  tdd  "\nenabled = false\n')
        self.assertIn("tdd: configured exclusion detected", "\n".join(self.filter_lines(self.doctor())))
        self.config('[[skills.config]]\nname = "tdd"\nenabled = false\n'
                    '[[skills.config]]\npath = "' + document + '"\nenabled = true\n')
        self.assertNotIn("configured exclusion detected", "\n".join(self.filter_lines(self.doctor())))
        self.config('[[skills.config]]\npath = "' + document + '"\nenabled = true\n'
                    '[[skills.config]]\nname = "tdd"\nenabled = false\n')
        self.assertIn("tdd: configured exclusion detected", "\n".join(self.filter_lines(self.doctor())))

    def test_malformed_skill_entries_warn_with_fix_without_guessing(self):
        for text in ('skills = "bad"', '[skills]\nconfig = "bad"', '[skills]\nconfig = [1]',
                     '[[skills.config]]\nname = "tdd"\nenabled = "false"',
                     '[[skills.config]]\npath = 1\nenabled = false',
                     '[[skills.config]]\nname = 1\nenabled = false',
                     '[[skills.config]]\nname = "tdd"'):
            with self.subTest(text=text):
                self.config(text)
                result = self.doctor()
                lines = self.filter_lines(result)
                self.assertTrue(any("invalid skills.config" in line and "exclusions unknown" in line
                                    for line in lines), result.stdout)
                self.assertNotIn("configured exclusion detected", "\n".join(lines))
                self.assertRegex(result.stdout, r"invalid skills.config[^\n]*\n     fix: ")
                self.assertNotIn("Traceback", result.stderr)

    def test_codex_0166_skills_config_rs_205_212_216_skips_only_that_entry(self):
        for skipped in ('name = " "', 'name = "team-lead"\npath = "/other/SKILL.md"', ''):
            with self.subTest(skipped=skipped):
                self.config('[[skills.config]]\nname = "tdd"\nenabled = false\n'
                            '[[skills.config]]\n' + skipped + '\nenabled = false\n')
                result = self.doctor()
                lines = self.filter_lines(result)
                self.assertIn('tdd: configured exclusion detected', result.stdout)
                self.assertTrue(any(line.startswith('note') and 'skipped' in line for line in lines), result.stdout)
                self.assertNotIn('invalid skills.config', result.stdout)

    def test_removed_exclusion_and_enabled_skill_report_no_exclusion(self):
        self.config('[[skills.config]]\nname = "tdd"\nenabled = false\n')
        self.assertIn("configured exclusion detected", "\n".join(self.filter_lines(self.doctor())))
        for text in ('', '[[skills.config]]\nname = "tdd"\nenabled = true\n'):
            self.config(text)
            self.assertNotIn("configured exclusion detected", "\n".join(self.filter_lines(self.doctor())))

    def test_missing_config_reports_unknown_scope_without_exclusion(self):
        self.assertFalse((self.home / ".codex/config.toml").exists())
        lines = self.filter_lines(self.doctor())
        self.assertNotIn("configured exclusion detected", "\n".join(lines))
        self.assertFalse(any(line.startswith("PASS") for line in lines))

    def test_malformed_toml_and_utf8_warn_with_fix_and_exit_zero(self):
        for raw in (b'model = "secret-value\n', b'\xff'):
            (self.home / ".codex/config.toml").write_bytes(raw)
            result = self.doctor()
            self.filter_lines(result)
            self.assertRegex(result.stdout, r"WARN skill filters codex: ~/.codex/config.toml is not valid "
                                           r"UTF-8 TOML; exclusions unknown\n     fix: repair the TOML")
            self.assertNotIn("secret-value", result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_unreadable_mode_zero_config_is_unknown(self):
        config = self.config('[[skills.config]]\nname = "tdd"\nenabled = false\n')
        config.chmod(0)
        self.addCleanup(config.chmod, 0o600)
        result = self.doctor()
        lines = self.filter_lines(result)
        self.assertTrue(any("cannot be read; exclusions unknown" in line for line in lines), result.stdout)
        self.assertNotIn("configured exclusion detected", "\n".join(lines))
        self.assertRegex(result.stdout, r"cannot be read; exclusions unknown\n     fix: restore read access")

    def test_linked_dotfiles_config_is_read_with_no_warning_merely_for_the_link(self):
        target = self.home / 'dotfiles/config.toml'
        target.parent.mkdir()
        config = self.home / '.codex/config.toml'
        config.symlink_to(target)
        for text, warnings in (('[[skills.config]]\nname = "tdd"\nenabled = false\n', 1), ('', 0)):
            with self.subTest(text=text):
                target.write_text(text)
                log = self.root / 'dotfiles-audit.log'
                result = self.run_cmd(PYTHON, '-B', '-I', self.clone / 'tests/helpers/audited_doctor.py', log,
                                      self.home / '.agents/mifal/lib', config, check=False)
                lines = self.filter_lines(result)
                self.assertEqual(sum(line.startswith('WARN') for line in lines), warnings, result.stdout)
                self.assertEqual('tdd: configured exclusion detected' in result.stdout, bool(warnings))
                self.assertIn('open ' + str(target), log.read_text())

    def test_linked_config_to_credentials_is_unknown_without_reading_its_target(self):
        target = self.home / '.codex/auth.json'
        target.write_text('[[skills.config]]\nname = "tdd"\nenabled = false\n')
        (self.home / '.codex/config.toml').symlink_to(target)
        log = self.root / 'linked-config-audit.log'
        result = self.run_cmd(PYTHON, '-B', '-I', self.clone / 'tests/helpers/audited_doctor.py', log,
                              self.home / '.agents/mifal/lib', self.home / '.codex/config.toml', check=False)
        lines = self.filter_lines(result)
        self.assertTrue(any("credential, token or auth path; exclusions unknown" in line for line in lines),
                        result.stdout)
        self.assertNotIn("configured exclusion detected", "\n".join(lines))
        self.assertNotIn('open ' + str(target), log.read_text())
        self.assertNotIn('open ' + str(self.home / '.codex/config.toml'), log.read_text())

    def test_linked_non_toml_targets_stay_unopened_under_the_independent_auditor(self):
        config = self.home / '.codex/config.toml'
        for rel in ('.aws/credentials', '.claude.json', '.netrc', '.config/gh/hosts.yml',
                    '.ssh/id_ed25519', 'dotfiles/settings.txt'):
            with self.subTest(path=rel):
                target = self.home / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('[[skills.config]]\nname = "tdd"\nenabled = false\n')
                config.symlink_to(target)
                try:
                    log = self.root / 'non-toml-audit.log'
                    result = self.run_cmd(PYTHON, '-B', '-I', self.clone / 'tests/helpers/audited_doctor.py',
                                          log, self.home / '.agents/mifal/lib', config, check=False)
                    lines = self.filter_lines(result)
                    self.assertTrue(any('exclusions unknown' in line for line in lines), result.stdout)
                    self.assertNotIn('configured exclusion detected', '\n'.join(lines))
                    self.assertNotIn('open ' + str(config), log.read_text())
                    self.assertNotIn('open ' + str(target), log.read_text())
                finally:
                    config.unlink()

    def test_dangling_config_link_says_codex_reads_no_settings_without_opening_it(self):
        config = self.home / '.codex/config.toml'
        config.symlink_to(self.home / 'missing.toml')
        log = self.root / 'dangling-audit.log'
        result = self.run_cmd(PYTHON, '-B', '-I', self.clone / 'tests/helpers/audited_doctor.py', log,
                              self.home / '.agents/mifal/lib', config, check=False)
        self.filter_lines(result)
        self.assertIn('points to a missing file; Codex 0.166.0 reads no settings from it',
                      result.stdout)
        self.assertNotIn('reads no settings from it; exclusions unknown', result.stdout)
        self.assertNotIn('open ' + str(config), log.read_text())
        self.assertRegex(result.stdout, r'Codex 0.166.0 reads no settings from it[^\n]*\n     fix: ')

    def test_relative_tilde_and_link_alias_select_the_document_not_the_folder(self):
        alias = self.home / 'pool-alias'
        alias.symlink_to(self.home / '.agents/skills')
        for path in ('../.agents/skills/tdd/SKILL.md', '~/.agents/skills/tdd/SKILL.md',
                     str(alias / 'tdd/SKILL.md'), str(alias / '../.agents/skills/tdd/SKILL.md')):
            self.config('[[skills.config]]\npath = "' + path + '"\nenabled = false\n')
            self.assertIn("tdd: configured exclusion detected", "\n".join(self.filter_lines(self.doctor())))
        self.config('[[skills.config]]\npath = "' + str(self.home / '.agents/skills/tdd') +
                    '"\nenabled = false\n')
        self.assertNotIn("configured exclusion detected", "\n".join(self.filter_lines(self.doctor())))

    def test_secret_values_and_unknown_skill_selectors_never_reach_output(self):
        self.config('model = "sk-secret-model"\n'
                    '[mcp_servers.example]\nenv = { TOKEN = "sk-secret-token" }\n'
                    '[[skills.config]]\nname = "sk-secret-selector"\nenabled = false\n'
                    '[[skills.config]]\npath = "/sk-secret-path/SKILL.md"\nenabled = false\n'
                    '[[skills.config]]\nname = "tdd"\nenabled = false\n'
                    '[[skills.config]]\nname = "team-lead"\nenabled = false\n')
        result = self.doctor()
        lines = self.filter_lines(result)
        self.assertEqual(sum("configured exclusion detected" in line for line in lines), 2, result.stdout)
        self.assertNotIn("sk-secret", result.stdout + result.stderr)

    def test_recorded_homes_are_audited_instead_of_shell_codex_home(self):
        other = self.home / 'codex-work'
        self.install('--home', 'codex=' + str(other))
        self.config('[[skills.config]]\nname = "tdd"\nenabled = false\n')
        self.config('[[skills.config]]\nname = "team-lead"\nenabled = false\n', other)
        unserved = self.home / 'codex-unserved'
        unserved.mkdir()
        self.config('invalid secret-unserved', unserved)
        log = self.root / 'homes-audit.log'
        result = self.run_cmd(PYTHON, '-B', '-I', self.clone / 'tests/helpers/audited_doctor.py', log,
                              self.home / '.agents/mifal/lib', self.home / '.codex/config.toml',
                              other / 'config.toml', CODEX_HOME=str(unserved), check=False)
        lines = self.filter_lines(result)
        exclusions = [line for line in lines if 'configured exclusion detected' in line]
        self.assertEqual(len(exclusions), 2, result.stdout)
        self.assertTrue(any('tdd:' in line and '~/.codex/config.toml' in line for line in exclusions))
        self.assertTrue(any('team-lead:' in line and '~/codex-work/config.toml' in line for line in exclusions))
        self.assertFalse(any('codex-unserved/config.toml' in line for line in lines))
        events = log.read_text().splitlines()
        self.assertIn('open ' + str(other / 'config.toml'), events)
        self.assertIn('open ' + str(self.home / '.codex/config.toml'), events)
        self.assertNotIn('open ' + str(unserved / 'config.toml'), events)

    def test_home_with_config_delivered_guide_is_also_audited(self):
        root = self.home / 'codex-linked'
        root.mkdir()
        shared = self.home / 'shared-rules.md'
        shared.write_text('Personal rules\n')
        (root / 'AGENTS.md').symlink_to(shared)
        self.install('--home', 'codex=' + str(root))
        config = root / 'config.toml'
        config.write_text(config.read_text() + '\n[[skills.config]]\nname = "tdd"\nenabled = false\n')
        result = self.doctor()
        lines = self.filter_lines(result)
        self.assertTrue(any('tdd: configured exclusion detected in ~/codex-linked/config.toml' in line
                            for line in lines), result.stdout)

    def test_unreadable_config_delivered_guide_fails_with_one_restore_access_fix(self):
        root = self.home / 'codex-linked'
        root.mkdir()
        shared = self.home / 'shared-rules.md'
        shared.write_text('Personal rules\n')
        (root / 'AGENTS.md').symlink_to(shared)
        self.install('--home', 'codex=' + str(root))
        config = root / 'config.toml'
        config.chmod(0)
        self.addCleanup(config.chmod, 0o600)
        result = self.doctor()
        self.assertIn('~/codex-linked/config.toml cannot be read; exclusions unknown', result.stdout)
        self.assertNotIn('Traceback', result.stdout + result.stderr)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('FAIL guide codex: cannot read ~/codex-linked/config.toml; Guide is not delivered',
                      result.stdout)
        self.assertEqual(result.stdout.count('fix: restore read access to ~/codex-linked/config.toml'), 1,
                         result.stdout)

    def test_mode_zero_codex_home_reports_unknown_with_fix_without_traceback(self):
        root = self.home / '.codex'
        root.chmod(0)
        self.addCleanup(root.chmod, 0o700)
        result = self.doctor()
        self.assertNotIn('Traceback', result.stdout + result.stderr)
        self.assertRegex(result.stdout, r'(?m)^(WARN|FAIL) guide codex: .*unknown[^\n]*\n     fix: ')

    def test_linked_config_delivered_guide_passes_when_key_is_intact(self):
        root = self.home / 'codex-key'
        root.mkdir()
        shared = self.home / 'shared.md'
        shared.write_text('Personal rules\n')
        (root / 'AGENTS.md').symlink_to(shared)
        self.install('--home', 'codex=' + str(root))
        config = root / 'config.toml'
        target = self.home / 'key.toml'
        config.rename(target)
        config.symlink_to(target)
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS guide codex: Mifal's developer_instructions key in ~/codex-key/config.toml, as installed",
                      result.stdout)
        target.write_bytes(b'\xff')
        result = self.doctor()
        self.assertNotIn('Traceback', result.stdout + result.stderr)
        self.assertIn('FAIL guide codex: ~/codex-key/config.toml is not UTF-8 TOML any more', result.stdout)


class OtherSkillFilters(Doctor):
    def setUp(self):
        Sandbox.setUp(self)
        self.herdr_schema(SCHEMA.read_text())
        self.harness_fakes(*HARNESSES)
        self.fake('agent-browser', 'exit 0')

    def five_fixtures(self, name, version, key, hidden, filename='settings.json', variable=None):
        self.install()
        root = self.home / RULES[name].rsplit('/', 1)[0]
        config = root / filename
        hidden['unrelated'] = 'sk-secret-other-value'
        config.write_text(json.dumps(hidden))
        log = self.root / 'settings-audit.log'
        allowed = [root / filename]
        result = self.run_cmd(PYTHON, '-B', '-I', self.clone / 'tests/helpers/audited_doctor.py', log,
                              self.home / '.agents/mifal/lib', *allowed, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, rf'WARN skill filters {name}: tdd: configured exclusion detected[^\n]*{filename}[^\n]*{key}')
        self.assertRegex(result.stdout, r'configured exclusion detected[^\n]*\n     fix: ')
        self.assertIn(version, result.stdout)
        self.assertNotIn('sk-secret', result.stdout + result.stderr)
        self.assertIn('open ' + str(config), log.read_text())
        self.assertNotIn('connect ', log.read_text())
        processes = [line for line in log.read_text().splitlines() if line.startswith('exec ')]
        config.write_text('{"unrelated":"sk-secret-other-value"}')
        clear_log = self.root / 'clear-audit.log'
        clear = self.run_cmd(PYTHON, '-B', '-I', self.clone / 'tests/helpers/audited_doctor.py', clear_log,
                             self.home / '.agents/mifal/lib', *allowed)
        self.assertNotIn('configured exclusion detected', clear.stdout)
        self.assertEqual(processes, [line for line in clear_log.read_text().splitlines() if line.startswith('exec ')])
        if name == 'droid':
            config.write_text('{/* ordinary comment */"unrelated":"https://sk-secret/"}')
            commented = self.doctor()
            self.assertEqual(commented.returncode, 0, commented.stdout + commented.stderr)
            self.assertNotIn('WARN skill filters droid:', commented.stdout)
            self.assertNotIn('sk-secret', commented.stdout + commented.stderr)
        config.write_text('{bad json')
        malformed = self.doctor()
        self.assertEqual(malformed.returncode, 0, malformed.stdout + malformed.stderr)
        self.assertRegex(malformed.stdout, rf'WARN skill filters {name}:.*unknown[^\n]*\n     fix: ')
        self.assertNotIn('Traceback', malformed.stderr)
        config.chmod(0)
        try:
            denied = self.doctor()
            self.assertEqual(denied.returncode, 0, denied.stdout + denied.stderr)
            self.assertRegex(denied.stdout, rf'WARN skill filters {name}:.*unknown[^\n]*\n     fix: ')
            self.assertNotIn('Traceback', denied.stderr)
        finally:
            config.chmod(0o600)
        self.setUp()
        custom = self.home / ('custom-' + name)
        if variable:
            self.install(**{variable: str(custom)})
        else:
            self.install('--home', name + '=' + str(custom))
        (custom / filename).write_text(json.dumps(hidden))
        default = self.home / RULES[name].rsplit('/', 1)[0] / filename
        default.parent.mkdir(parents=True, exist_ok=True)
        default.write_text('{bad default must not be opened')
        override_log = self.root / 'override-audit.log'
        overridden = self.run_cmd(PYTHON, '-B', '-I', self.clone / 'tests/helpers/audited_doctor.py', override_log,
                                 self.home / '.agents/mifal/lib', custom / filename, check=False)
        self.assertEqual(overridden.returncode, 0, overridden.stdout + overridden.stderr)
        self.assertIn('tdd: configured exclusion detected', overridden.stdout)
        self.assertIn('custom-' + name, overridden.stdout)
        self.assertNotIn('open ' + str(default) + '\n', override_log.read_text())
        self.assertNotIn('sk-secret', overridden.stdout + overridden.stderr)

    def test_claude_five_user_settings_fixtures(self):
        self.five_fixtures('claude', 'Claude Code 2.1.316', 'skillOverrides',
                           {'skillOverrides': {'tdd': 'off'}}, variable='CLAUDE_CONFIG_DIR')

    def test_droid_five_user_settings_fixtures(self):
        self.five_fixtures('droid', 'Droid 1.1.0', 'disabledSkills', {'disabledSkills': ['TDD']})

    def test_pi_five_user_settings_fixtures(self):
        self.five_fixtures('pi', 'Pi 1.4.0', 'skills', {'skills': ['!tdd']}, variable='PI_CODING_AGENT_DIR')

    def test_opencode_five_user_settings_fixtures(self):
        self.five_fixtures('opencode', 'OpenCode 1.19.4', 'permission.skill',
                           {'permission': {'skill': {'t*': 'deny'}}}, 'opencode.json', 'OPENCODE_CONFIG_DIR')

    def test_all_five_plain_homes_keep_the_baseline_warn_set_and_state_coverage(self):
        self.install()
        for have_settings in (False, True):
            if have_settings:
                for name in HARNESSES:
                    root = self.home / RULES[name].rsplit('/', 1)[0]
                    (root / ('config.toml' if name == 'codex' else 'opencode.json' if name == 'opencode' else 'settings.json')).write_text(
                        'model = "sk-secret"' if name == 'codex' else '{"unrelated":"sk-secret"}')
            result = self.doctor()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual([line for line in result.stdout.splitlines() if line.startswith('WARN')],
                             ['WARN engine: completeness could not be checked: the Manifest records no clone or revision'])
            for name, version in zip(HARNESSES, ('Claude Code 2.1.316', 'Codex 0.166.0', 'Droid 1.1.0', 'Pi 1.4.0', 'OpenCode 1.19.4')):
                self.assertRegex(result.stdout, rf'note skill filters {name}:.*supports {re.escape(version)}')
            self.assertNotIn('sk-secret', result.stdout + result.stderr)

    def test_pi_gitignore_reads_are_declared_and_failures_are_unknown(self):
        self.install()
        ignore = self.home / '.agents/skills/.gitignore'
        ignore.write_text('TDD/\n!tdd/SKILL.md\n')
        log = self.root / 'ignore-audit.log'
        result = self.run_cmd(PYTHON, '-B', '-I', self.clone / 'tests/helpers/audited_doctor.py', log,
                              self.home / '.agents/mifal/lib', ignore)
        self.assertRegex(result.stdout, r'WARN skill filters pi: tdd: configured exclusion detected[^\n]*\.gitignore')
        self.assertIn('open ' + str(ignore), log.read_text())
        ignore.write_text('tdd/\n!tdd/\n')
        self.assertNotIn('configured exclusion detected', self.doctor().stdout)
        ignore.write_bytes(b'\xff')
        self.assertRegex(self.doctor().stdout, r'WARN skill filters pi:.*UTF-8.*unknown')
        ignore.chmod(0)
        try:
            result = self.doctor()
            self.assertRegex(result.stdout, r'WARN skill filters pi:.*cannot be read.*unknown[^\n]*\n     fix: ')
            self.assertNotIn('Traceback', result.stderr)
        finally:
            ignore.chmod(0o600)


class AuditGuards(Doctor):
    def test_credentials_in_each_recorded_custom_home_are_independently_refused(self):
        paths, args = [], []
        for name in HARNESSES:
            root = self.home / ('alternate-' + name)
            args.extend(['--home', name + '=' + str(root)])
            paths.append(root / ('.credentials.json' if name == 'claude' else 'auth.json'))
        self.install(*args)
        configs = [os.path.join(rec['root'], 'config.toml') for rec in self.manifest()['harnesses']['codex']
                   if rec['status'] == 'wired']
        for path in paths:
            with self.subTest(path=path.name):
                path.write_text('placeholder')
                result = self.probe('print("doctor reached the probe")\nopen(' + repr(str(path)) + ').read()', configs)
                self.assertIn('doctor reached the probe', result.stdout)
                self.assertIn('forbidden settings or credential read', result.stderr)

    def test_new_settings_names_are_forbidden_without_a_declared_allowance(self):
        for rel in ('.config/opencode/config.json', '.config/opencode/opencode.jsonc', '.agents/skills/.gitignore'):
            with self.subTest(path=rel):
                path = self.home / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{}')
                self.probe('open(' + repr(str(path)) + ').read()')
                path.unlink()

    def test_new_agent_credentials_are_independently_refused(self):
        for rel in ('.factory/auth.json', '.factory/credentials.json', '.pi/agent/oauth.json', '.config/opencode/auth.json'):
            with self.subTest(path=rel):
                path = self.home / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('placeholder')
                self.probe('open(' + repr(str(path)) + ').read()')
    def test_audit_independently_refuses_review_306_credential_fixtures(self):
        for rel in ('.aws/credentials', '.claude.json', '.netrc', '.config/gh/hosts.yml', '.ssh/id_ed25519'):
            with self.subTest(path=rel):
                path = self.home / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('placeholder\n')
                self.probe('open(' + repr(str(path)) + ').read()')

    def probe(self, operation, config=None):
        helper = str(self.clone / 'tests/helpers/audited_doctor.py')
        log = self.root / 'probe-audit.log'
        configs = config if isinstance(config, list) else [config or self.home / '.codex/config.toml']
        argv = [helper, str(log), str(self.home / '.agents/mifal/lib'),
                *map(str, configs)]
        script = ('import runpy, sys\nsys.argv = ' + repr(argv) + '\n'
                  'try:\n    runpy.run_path(sys.argv[0])\n'
                  'except SystemExit as e:\n    assert e.code == 0\n' + operation)
        result = self.run_cmd(PYTHON, '-B', '-I', '-c', script, check=False)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RuntimeError: forbidden', result.stderr)
        return result

    def test_audit_refuses_credential_names_even_when_they_link_to_public_data(self):
        target = self.home / 'public.txt'
        target.write_text('placeholder\n')
        credential = self.home / '.codex/auth.json'
        credential.symlink_to(target)
        self.probe('open(' + repr(str(credential)) + ').read()')

    def test_declared_link_target_is_allowed_but_another_settings_file_is_refused(self):
        target = self.home / 'dotfiles/config.toml'
        target.parent.mkdir()
        target.write_text('model = "placeholder"\n')
        (self.home / '.codex/config.toml').symlink_to(target)
        other = self.home / 'other/config.toml'
        other.parent.mkdir()
        other.write_text('model = "placeholder"\n')
        result = self.probe('open(' + repr(str(target)) + ').read()\nprint("resolved target read")\n'
                            'open(' + repr(str(other)) + ').read()')
        self.assertIn('resolved target read', result.stdout)

    def test_audit_refuses_credentials_and_undeclared_settings_even_through_a_link(self):
        for rel in PRIVATE + ('.claude/settings.json', '.factory/settings.json', '.config/opencode/opencode.json'):
            path = self.home / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('secret\n')
            self.probe('open(' + repr(str(path)) + ').read()')
        link = self.home / '.codex/config.toml'
        link.symlink_to(self.home / '.codex/auth.json')
        self.probe('open(' + repr(str(link)) + ').read()')

    def test_audit_refuses_writes_even_to_the_declared_config(self):
        path = self.home / '.codex/config.toml'
        self.probe('open(' + repr(str(path)) + ', "w").write("changed")')
        self.probe('import os\nos.open(' + repr(str(path)) + ', os.O_WRONLY | os.O_CREAT)')
        self.probe('import os\nos.mkdir(' + repr(str(self.home / 'new-dir')) + ')')

    def test_audit_refuses_extra_processes_even_another_python_invocation(self):
        self.probe('import subprocess\nsubprocess.run([sys.executable, "-c", "pass"])')

    def test_audit_refuses_socket_creation(self):
        self.probe('import socket\nsocket.socket()')


class ReadOnly(Doctor):
    def test_the_doctor_writes_nothing_runs_no_harness_and_uses_no_network(self):
        for name in NETWORK:
            self.fake(name, "")
        calls = len(self.called())
        before = snapshot(self.home)
        self.assertEqual(self.doctor().returncode, 0)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual([c for c in self.called()[calls:] if not c.startswith("herdr ")], [])

    def test_the_doctor_opens_only_declared_settings_no_credentials_and_adds_no_processes(self):
        for rel in PRIVATE:
            (self.home / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.home / rel).write_text("secret\n")
        log = self.root / "audit.log"
        config = self.home / '.codex/config.toml'
        config.write_text('model = "sk-secret-model"\n[[skills.config]]\nname = "tdd"\nenabled = false\n')
        result = self.run_cmd(PYTHON, "-B", "-I", self.clone / "tests/helpers/audited_doctor.py", log,
                              self.home / ".agents/mifal/lib", config, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = log.read_text().splitlines()
        self.assertTrue([e for e in events if e.startswith("open ")])
        opened = [e for e in events if e.startswith("open ") and any(e.endswith(rel) for rel in PRIVATE)]
        self.assertEqual(opened, [])
        self.assertIn('open ' + str(config), events)
        self.assertIn('tdd: configured exclusion detected', result.stdout)
        self.assertNotIn('sk-secret', result.stdout + result.stderr)
        self.assertEqual([e for e in events if e.startswith("connect ")], [])
        processes = [e for e in events if e.startswith('exec ')]
        config.unlink()
        baseline_log = self.root / 'audit-without-settings.log'
        baseline = self.run_cmd(PYTHON, '-B', '-I', self.clone / 'tests/helpers/audited_doctor.py', baseline_log,
                                self.home / '.agents/mifal/lib', config)
        self.assertEqual(processes, [e for e in baseline_log.read_text().splitlines() if e.startswith('exec ')])
        self.assertNotIn('configured exclusion detected', baseline.stdout)


class Completeness(test_update.Update):
    """The doctor compares the engine files the recorded revision installs with what the Manifest owns."""

    def doctor(self):
        return self.mifal("doctor", check=False)

    def engine_lines(self, result):
        return [line for line in result.stdout.splitlines() if line.startswith(("WARN engine", "FAIL engine", "PASS engine"))]

    def test_the_only_command_it_adds_is_one_local_git_ls_tree_of_the_recorded_revision_and_it_writes_nothing(self):
        self.fake("git", 'exec /usr/bin/git "$@"')
        rev = self.manifest()["source"]["revision"]
        calls, before = len(self.called()), snapshot(self.home)
        self.assertEqual(self.doctor().returncode, 0)
        self.assertEqual([c for c in self.called()[calls:] if c.startswith("git ")],
                         [f"git -C {self.clone} ls-tree -r -z --name-only {rev}"])
        self.assertEqual(snapshot(self.home), before)

    def test_under_the_audit_hook_it_runs_that_one_git_command_and_opens_no_private_file_or_socket(self):
        for rel in PRIVATE:
            (self.home / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.home / rel).write_text("secret\n")
        log = self.root / "audit.log"
        result = self.run_cmd(PYTHON, "-B", "-I", self.clone / "tests/helpers/audited_doctor.py", log,
                              self.home / ".agents/mifal/lib", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = log.read_text().splitlines()
        self.assertEqual([e for e in events if e.startswith("open ") and any(e.endswith(rel) for rel in PRIVATE)], [])
        self.assertEqual([e for e in events if e.startswith("connect ")], [])
        self.assertEqual([e for e in events if e.startswith("exec ") and "git" in e and "ls-tree" not in e], [])
        self.assertEqual(len([e for e in events if e.startswith("exec ") and "ls-tree" in e]), 1)

    def test_a_healthy_install_shows_no_completeness_line(self):
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.engine_lines(result), [])

    def test_missing_engine_files_warn_once_with_the_count_and_the_fix_and_write_nothing(self):
        self.drop_licences()
        before = snapshot(self.home)
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(len(self.engine_lines(result)), 1, result.stdout)
        lines = result.stdout.splitlines()
        at = next(i for i, line in enumerate(lines) if line.startswith("WARN engine"))
        self.assertIn("16 file(s)", lines[at])
        self.assertEqual(lines[at + 1].strip(), "fix: run mifal update")
        self.assertEqual(snapshot(self.home), before)

    def test_a_missing_clone_says_completeness_could_not_be_checked(self):
        shutil.rmtree(self.clone)
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(len(self.engine_lines(result)), 1, result.stdout)
        self.assertIn("completeness could not be checked", self.engine_lines(result)[0])
        self.assertIn("fix: ", result.stdout.split("completeness could not be checked", 1)[1].splitlines()[1])

    def test_an_unreadable_revision_says_completeness_could_not_be_checked(self):
        path = self.home / ".agents/mifal/install-manifest.json"
        data = json.loads(path.read_text())
        data["source"]["revision"] = "0" * 40
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(len(self.engine_lines(result)), 1, result.stdout)
        self.assertIn("completeness could not be checked", self.engine_lines(result)[0])

    def test_a_failed_enumeration_says_completeness_could_not_be_checked(self):
        self.fake("git", "exit 1")
        result = self.doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(len(self.engine_lines(result)), 1, result.stdout)
        self.assertIn("completeness could not be checked", self.engine_lines(result)[0])


class Warnings(Doctor):
    def test_factory_home_override_warns_that_droid_may_not_read_its_wiring(self):
        result = self.doctor(FACTORY_HOME_OVERRIDE=str(self.home / "factory-elsewhere"))
        self.assertRegex(result.stdout, r"(?m)^WARN droid: FACTORY_HOME_OVERRIDE")

    def test_a_root_variable_outside_home_warns(self):
        outside = self.root / "outside-codex"
        outside.mkdir()
        result = self.doctor(outside=("CODEX_HOME",), CODEX_HOME=str(outside))
        self.assertRegex(result.stdout, r"(?m)^WARN CODEX_HOME .* outside your home folder")


if __name__ == "__main__":
    unittest.main()
