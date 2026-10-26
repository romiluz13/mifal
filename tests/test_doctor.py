import json
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
# Files a harness keeps settings, tokens or credentials in. The doctor never opens any of them.
PRIVATE = (".claude/settings.json", ".claude/.credentials.json", ".codex/auth.json", ".codex/config.toml",
           ".factory/settings.json", ".pi/agent/auth.json", ".config/opencode/opencode.json",
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
        self.assertIn("./install.sh --overwrite-edits", fix)
        self.assertIn("OpenCode then reads ~/.config/opencode/AGENTS.md, not ~/.claude/CLAUDE.md", fix)
        self.assertTrue(fix.startswith("run ./install.sh --overwrite-edits in your Mifal clone; "), fix)
        self.assertNotIn("OPENCODE_CONFIG_DIR=", fix)
        self.assertNotIn("not wired yet", result.stdout)
        self.install("--overwrite-edits")
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
            "run OPENCODE_CONFIG_DIR=" + root + " ./install.sh --overwrite-edits in your Mifal clone; "), fix)
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


class ReadOnly(Doctor):
    def test_the_doctor_writes_nothing_runs_no_harness_and_uses_no_network(self):
        for name in NETWORK:
            self.fake(name, "")
        calls = len(self.called())
        before = snapshot(self.home)
        self.assertEqual(self.doctor().returncode, 0)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual([c for c in self.called()[calls:] if not c.startswith("herdr ")], [])

    def test_the_doctor_opens_no_settings_or_credential_file_and_no_socket(self):
        for rel in PRIVATE:
            (self.home / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.home / rel).write_text("secret\n")
        log = self.root / "audit.log"
        result = self.run_cmd(PYTHON, "-B", "-I", self.clone / "tests/helpers/audited_doctor.py", log,
                              self.home / ".agents/mifal/lib", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = log.read_text().splitlines()
        self.assertTrue([e for e in events if e.startswith("open ")])
        opened = [e for e in events if e.startswith("open ") and any(e.endswith(rel) for rel in PRIVATE)]
        self.assertEqual(opened, [])
        self.assertEqual([e for e in events if e.startswith("connect ")], [])
        self.assertEqual([e for e in events if e.startswith("exec ") and not re.search(r"herdr|python", e)], [])


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
        self.assertIn("9 file(s)", lines[at])
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
