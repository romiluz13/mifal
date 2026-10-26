"""Option C: a named Codex Home whose AGENTS.md links to a shared file gets the Guide as one Mifal-marked
developer_instructions key at the top of its own config.toml, in a disposable HOME."""

import json
import os
import stat
import unittest

from support import Sandbox, snapshot
from test_tomli import vendored

SHARED = "my shared rules\n"
SECRET = "sentinel-value-never-printed"
CONFIG = f'model = "{SECRET}"\n\n[profiles.fast]\nmodel_reasoning_effort = "low"\n'


class OptionC(Sandbox):
    def setUp(self):
        super().setUp()
        (self.home / ".ai").mkdir()
        self.shared = self.home / ".ai/AGENTS.md"
        self.shared.write_text(SHARED)
        self.workhome, self.personal = self.home / ".codex-work", self.home / ".codex-personal"
        for root in (self.workhome, self.personal):
            root.mkdir()
            (root / "AGENTS.md").symlink_to(self.shared)

    def guide(self):
        return (self.clone / "guide/AGENTS.md").read_bytes().decode("utf-8")

    def flags(self, *roots):
        args = [r for r in roots if isinstance(r, str)]
        roots = [r for r in roots if not isinstance(r, str)]
        return [f for root in roots or (self.workhome,) for f in ("--home", f"codex={root}")] + args

    def install_c(self, *roots, **kw):
        result = self.install(*self.flags(*roots), **kw)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        return result

    def parsed(self, root):
        return vendored().loads((root / "config.toml").read_text(encoding="utf-8"))

    def record(self, root):
        return next(r for r in self.manifest()["harnesses"]["codex"] if r["root"] == str(root))


class Install(OptionC):
    def test_a_named_linked_home_without_a_config_gets_one_holding_exactly_the_guide(self):
        result = self.install_c()
        self.assertEqual(self.parsed(self.workhome), {"developer_instructions": self.guide()})
        self.assertTrue((self.workhome / "AGENTS.md").is_symlink())
        self.assertEqual(os.readlink(self.workhome / "AGENTS.md"), str(self.shared))
        self.assertEqual(self.shared.read_text(), SHARED)
        self.assertTrue((self.workhome / "config.toml").read_text().startswith("# mifal:begin "))
        self.assertEqual(self.record(self.workhome)["status"], "wired")
        self.assertEqual(self.record(self.workhome)["delivery"], "config")
        self.assertIn("Wired: Codex", result.stdout)

    def test_an_existing_config_keeps_every_byte_after_the_block_and_a_private_backup_is_recorded(self):
        for name, original in (("lf", CONFIG.encode()), ("crlf", CONFIG.replace("\n", "\r\n").encode()),
                               ("non-ascii", f'# réglages ✓\nmodel = "{SECRET} ε"\n'.encode()),
                               ("no final newline", b'model = "x"')):
            with self.subTest(name=name):
                self.setUp()
                config = self.workhome / "config.toml"
                config.write_bytes(original)
                self.install_c()
                written = config.read_bytes()
                self.assertTrue(written.endswith(original))
                block = written[:-len(original)].decode()
                self.assertEqual(block.count("\r\n"), block.count("\n") if name == "crlf" else 0)
                expected = vendored().loads(original.decode())
                self.assertEqual(self.parsed(self.workhome), dict(expected, developer_instructions=self.guide()))
                entry = next(e for e in self.manifest()["entries"] if e["kind"] == "key")
                self.assertEqual(entry["path"], str(config.resolve()))
                backup = self.home / entry["backup"]
                self.assertEqual(backup.read_bytes(), original)
                self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
                self.assertIn("/.agents/mifal/backup/", entry["backup"])

    def test_a_failed_install_restores_the_config_and_leaves_no_backup(self):
        (self.workhome / "config.toml").write_text(CONFIG)
        before = snapshot(self.home)
        result = self.install(*self.flags(self.workhome, self.personal), check=False,
                              MIFAL_TEST_FAIL_AT="before-publication")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("rolled back", result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_the_preview_names_the_path_and_key_and_writes_nothing(self):
        (self.workhome / "config.toml").write_text(CONFIG)
        before = snapshot(self.home)
        result = self.install_c(self.workhome, "--dry-run")
        self.assertIn("key ~/.codex-work/config.toml: developer_instructions", result.stdout.splitlines())
        self.assertIn("backup ~/.codex-work/config.toml -> ~/.agents/mifal/backup/", result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_adversarial_guide_text_reads_back_exactly(self):
        hostile = ('"""\n\'\'\' "quoted" \\ back\\slash\\\n  leading spaces\n\ttab\n line\\\n'
                   'trailing """"\n\x00\x07\x7f\r\n# mifal:end\n[table]\nkey = "v"\né 中 \U0001F600\n\n')
        for config in (None, CONFIG.replace("\n", "\r\n")):
            with self.subTest(crlf=config is not None):
                self.setUp()
                (self.clone / "guide/AGENTS.md").write_text(hostile, encoding="utf-8", newline="")
                if config:
                    (self.workhome / "config.toml").write_bytes(config.encode())
                self.install_c()
                self.assertEqual(self.parsed(self.workhome)["developer_instructions"], hostile)


class Refusals(OptionC):
    def refused(self, why, config=None, setup=None):
        if config is not None:
            (self.workhome / "config.toml").write_bytes(config.encode() if isinstance(config, str) else config)
        if setup:
            setup()
        before = snapshot(self.home)
        for args in ((), ("--dry-run",), ("--overwrite-edits",)):
            result = self.install(*self.flags(), *args, check=False)
            text = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, text)
            self.assertIn(f"~/.codex-work/config.toml: {why}", text)
            self.assertIn("Nothing was written.", text)
            self.assertNotIn(SECRET, text)
            self.assertNotIn("--overwrite-edits", text)
            self.assertEqual(snapshot(self.home), before)

    def test_an_existing_key_in_any_form_is_refused_with_nothing_written(self):
        forms = {
            "top level": f'developer_instructions = "{SECRET}"\n',
            "quoted key": f'"developer_instructions" = "{SECRET}"\n',
            "literal quoted key": f"'developer_instructions' = '{SECRET}'\n",
            "dotted": f'profiles.fast.developer_instructions = "{SECRET}"\n',
            "in a table": f'[agents.reviewer]\ndeveloper_instructions = """\n{SECRET}\n"""\n',
            "in a profile": f'[profiles.deep]\nmodel = "x"\ndeveloper_instructions = "{SECRET}"\n',
            "in an array of tables": f'[[roles]]\ndeveloper_instructions = "{SECRET}"\n',
            "in an inline table": f'profile = {{ developer_instructions = "{SECRET}" }}\n',
        }
        for name, config in forms.items():
            with self.subTest(form=name):
                self.setUp()
                self.refused("already sets developer_instructions, so Mifal adds none", config)

    def test_a_symlinked_config_is_refused_and_its_target_untouched(self):
        target = self.home / "dotfiles-config.toml"
        target.write_text(CONFIG)
        self.refused("is a symbolic link, and Mifal does not write through a link",
                     setup=lambda: (self.workhome / "config.toml").symlink_to(target))
        self.assertEqual(target.read_text(), CONFIG)

    def test_invalid_toml_is_refused_without_printing_any_value(self):
        for name, config in (("syntax", f'model = "{SECRET}\n'), ("duplicate", f'a = "{SECRET}"\na = 1\n'),
                             ("bom", b"\xef\xbb\xbf" + CONFIG.encode()), ("lone cr", b'a = 1\rb = 2\r'),
                             ("not utf-8", b'model = "\xff"\n')):
            with self.subTest(name=name):
                self.setUp()
                why = "is not UTF-8" if name == "not utf-8" else "does not parse as TOML"
                self.refused(f"{why}, so Mifal cannot add developer_instructions", config)

    def test_a_mifal_marker_this_install_did_not_write_is_refused(self):
        self.refused("holds a Mifal marker this install did not write",
                     "# mifal:begin version=0.0.1\n# mifal:end\n" + CONFIG)

    def test_a_linked_codex_home_nobody_named_is_still_refused(self):
        self.harness_fakes("codex")
        before = snapshot(self.home)
        result = self.install(check=False, CODEX_HOME=str(self.workhome))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("~/.codex-work/AGENTS.md: is a symbolic link to ~/.ai/AGENTS.md, and Mifal does not write "
                      "through a link", result.stdout)
        self.assertEqual(snapshot(self.home), before)


def hooks(*commands, event="SessionStart", handler=None):
    return json.dumps({"hooks": {event: [{"matcher": "startup", "hooks": [
        handler or {"type": "command", "command": c, "timeout": 5} for c in commands or [None]]}]}})


REFERENCES = "your SessionStart command references the Guide; no key was added"
UNCLASSIFIED = "it has a SessionStart hook Mifal cannot classify; no key was added"


class Hooks(OptionC):
    """The served Home's own hooks.json, read as data, decides whether the key may be written."""

    def hooked(self, text, root=None):
        root = root or self.workhome
        (root / "hooks.json").write_bytes(text.encode() if isinstance(text, str) else text)
        return root / "hooks.json"

    def pending(self, why, root=None):
        root = root or self.workhome
        hook = root / "hooks.json"
        held = hook.read_bytes() if hook.is_file() and not hook.is_symlink() else None
        result = self.install_c(root)
        self.assertFalse((root / "config.toml").exists())
        self.assertEqual(self.record(root)["status"], "pending")
        self.assertIn(f"pending codex: {self.show(root)}: {why}", result.stdout)
        self.assertNotIn("Wired: Codex", result.stdout)
        self.assertIn(f"Pending, not served until their hooks allow it: Codex at {self.show(root)}", result.stdout)
        if held is not None:
            self.assertEqual(hook.read_bytes(), held)
            for command in held.decode("utf-8", "replace").split('"command": "')[1:]:
                self.assertNotIn(command.split('"')[0], result.stdout + result.stderr)
        return result

    def show(self, path):
        return "~/" + str(path.relative_to(self.home))

    def keyed(self, root=None):
        self.install_c(root or self.workhome)
        self.assertEqual(self.parsed(root or self.workhome)["developer_instructions"], self.guide())
        self.assertEqual(self.record(root or self.workhome)["status"], "wired")

    def test_no_hooks_file_or_an_empty_session_start_is_clear(self):
        for text in (None, "{}", '{"hooks": {}}', '{"hooks": {"SessionStart": []}}',
                     '{"description": "x", "hooks": {"SessionStart": [{"hooks": []}]}}'):
            with self.subTest(text=text):
                self.setUp()
                if text is not None:
                    self.hooked(text)
                self.keyed()

    def test_a_session_start_command_naming_the_guide_in_any_spelling_is_pending(self):
        for command in ("cat ~/.agents/mifal/AGENTS.md", 'cat "$HOME/.agents/mifal/AGENTS.md"',
                        "cat ${HOME}/.agents/mifal/AGENTS.md", "cat '{home}/.agents/mifal/AGENTS.md'",
                        "cat {home}/.agents/mifal/AGENTS.md;echo",
                        "python3 -c 'print(open(\"~/.agents/mifal/AGENTS.md\").read())'"):
            with self.subTest(command=command):
                self.setUp()
                self.hooked(hooks(command.replace("{home}", str(self.home))))
                self.pending(REFERENCES)

    def test_a_lookalike_or_indirect_command_is_pending_for_review_not_called_a_reference(self):
        for command in ("cat ~/.agents/mifal/AGENTS.md.bak", "cat ~/.agents/mifal-old/AGENTS.md",
                        "cat ~/x.agents/mifal/AGENTS.md", "bash ~/bin/session-start.sh", "echo hello"):
            with self.subTest(command=command):
                self.setUp()
                self.hooked(hooks(command))
                result = self.pending(f"{self.show(self.workhome / 'hooks.json')}: {UNCLASSIFIED}")
                self.assertNotIn(REFERENCES, result.stdout)

    def test_a_session_start_handler_that_is_not_a_command_is_pending_for_review(self):
        for handler in ({"type": "prompt"}, {"type": "agent"},
                        {"type": "mcp_tool", "server": "s", "tool": "t"}):
            with self.subTest(handler=handler["type"]):
                self.setUp()
                self.hooked(hooks(handler=handler))
                self.pending(f"{self.show(self.workhome / 'hooks.json')}: {UNCLASSIFIED}")

    def test_a_guide_reference_in_another_event_is_clear(self):
        self.hooked(hooks("cat ~/.agents/mifal/AGENTS.md", event="PreToolUse"))
        self.keyed()

    def test_a_malformed_or_unsupported_hooks_file_is_unknown_and_gets_no_key(self):
        cases = {"invalid json": "{", "empty file": "", "not utf-8": b'{"hooks": "\xff"}',
                 "a list": "[]", "events outside hooks": '{"SessionStart": []}',
                 "hooks not an object": '{"hooks": []}', "session start not a list": '{"hooks": {"SessionStart": {}}}',
                 "group not an object": '{"hooks": {"SessionStart": [1]}}',
                 "unknown handler type": hooks(handler={"type": "script", "path": "x"}),
                 "command not a string": hooks(handler={"type": "command", "command": 1})}
        for name, text in cases.items():
            with self.subTest(name=name):
                self.setUp()
                hook = self.hooked(text)
                self.pending(f"Mifal cannot classify {self.show(hook)}, so it adds no key")

    def test_a_linked_hooks_file_is_unknown_and_its_target_is_not_read(self):
        target = self.home / "dotfiles-hooks.json"
        target.write_text(hooks("echo hi"))
        (self.workhome / "hooks.json").symlink_to(target)
        self.pending(f"Mifal cannot classify {self.show(self.workhome / 'hooks.json')}, so it adds no key")

    def test_a_pending_home_beside_a_clear_one_is_served_in_the_same_run_and_named_apart(self):
        self.hooked(hooks("cat ~/.agents/mifal/AGENTS.md"), self.personal)
        result = self.install_c(self.workhome, self.personal)
        self.assertEqual(self.record(self.workhome)["status"], "wired")
        self.assertEqual(self.record(self.personal)["status"], "pending")
        self.assertIn("Wired: Codex", result.stdout)
        self.assertIn("Pending, not served until their hooks allow it: Codex at ~/.codex-personal", result.stdout)
        self.assertFalse((self.personal / "config.toml").exists())


if __name__ == "__main__":
    unittest.main()
