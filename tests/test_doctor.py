import json
import re
import shutil
import unittest

from support import PYTHON, REPO, Sandbox, snapshot

HERDR_STATUS = json.dumps({"client": {"version": "0.9.5"}, "server": {"running": True, "version": "0.9.5"}})
SCHEMA = REPO / "tools/herdr_adapter/api-schema.json"
HARNESSES = ("claude", "codex", "droid", "pi", "opencode")
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


class Broken(Doctor):
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
