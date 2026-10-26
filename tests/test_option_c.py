"""Option C: a named Codex Home whose AGENTS.md links to a shared file gets the Guide as one Mifal-marked
developer_instructions key at the top of its own config.toml, in a disposable HOME."""

import json
import os
import stat
import unittest

from support import Sandbox, snapshot
from test_tomli import vendored
from test_update import Update

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
                (self.clone / "guide/AGENTS.md").write_bytes(hostile.encode("utf-8"))
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


def inline(*commands, event="SessionStart", handler=None):
    """The same hook as hooks(), written as a [hooks] table in config.toml."""
    body = "".join(f"[[hooks.{event}.hooks]]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in
                   (handler or {"type": "command", "command": c, "timeout": 5}).items()) for c in commands or [None])
    return f'[[hooks.{event}]]\nmatcher = "startup"\n{body}'


REFERENCES = "your SessionStart command references the Guide; no key was added"
UNCLASSIFIED = "it has a SessionStart hook Mifal cannot classify; no key was added"
INLINE_REFERENCES = "your [hooks] SessionStart command references the Guide; no key was added"
INLINE_UNCLASSIFIED = "it has a [hooks] SessionStart hook Mifal cannot classify; no key was added"


class Hooks(OptionC):
    """The served Home's own hooks.json, read as data, decides whether the key may be written."""

    def hooked(self, text, root=None):
        root = root or self.workhome
        (root / "hooks.json").write_bytes(text.encode() if isinstance(text, str) else text)
        return root / "hooks.json"

    def inlined(self, text, root=None):
        root = root or self.workhome
        (root / "config.toml").write_text(text)
        return root / "config.toml"

    def pending(self, why, root=None, status="pending"):
        root = root or self.workhome
        hook, config = root / "hooks.json", root / "config.toml"
        held = hook.read_bytes() if hook.is_file() and not hook.is_symlink() else None
        kept = config.read_bytes() if config.exists() else None
        result = self.install_c(root)
        self.assertEqual(config.read_bytes() if config.exists() else None, kept)
        self.assertEqual(self.record(root)["status"], status)
        self.assertIn(f"{status} codex: {self.show(root)}: {why}", result.stdout)
        self.assertNotIn("Wired: Codex", result.stdout)
        summary = {"pending": "Pending, not served until their hooks allow it",
                   "unknown": "Unknown, not served (Mifal cannot read their hooks)"}
        self.assertIn(f"{summary[status]}: Codex at {self.show(root)}", result.stdout)
        self.assertNotIn(summary["pending" if status == "unknown" else "unknown"], result.stdout)
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
                self.pending(f"Mifal cannot classify {self.show(hook)}, so it adds no key", status="unknown")

    def test_a_linked_hooks_file_is_unknown_and_its_target_is_not_read(self):
        target = self.home / "dotfiles-hooks.json"
        target.write_text(hooks("echo hi"))
        (self.workhome / "hooks.json").symlink_to(target)
        self.pending(f"Mifal cannot classify {self.show(self.workhome / 'hooks.json')}, so it adds no key",
                     status="unknown")

    def test_a_pending_home_beside_a_clear_one_is_served_in_the_same_run_and_named_apart(self):
        self.hooked(hooks("cat ~/.agents/mifal/AGENTS.md"), self.personal)
        result = self.install_c(self.workhome, self.personal)
        self.assertEqual(self.record(self.workhome)["status"], "wired")
        self.assertEqual(self.record(self.personal)["status"], "pending")
        self.assertIn("Wired: Codex", result.stdout)
        self.assertIn("Pending, not served until their hooks allow it: Codex at ~/.codex-personal", result.stdout)
        self.assertFalse((self.personal / "config.toml").exists())


class Lifecycle(Update, OptionC):
    """Update and uninstall of an installed key, against a local origin."""

    def setUp(self):
        super().setUp()
        self.config = self.workhome / "config.toml"
        self.config.write_text(CONFIG)
        self.install_c()
        self.keyed = self.config.read_text()
        self.backup = self.home / next(e for e in self.manifest()["entries"] if e["kind"] == "key")["backup"]

    def new_release(self):
        self.publish("a new release", VERSION="9.9.9\n", **{"guide/AGENTS.md": self.guide() + "One more rule.\n"})

    def edit_outside(self):
        self.config.write_text(self.config.read_text() + 'approval_policy = "never"\n')
        return CONFIG + 'approval_policy = "never"\n'

    def edit_inside(self):
        self.config.write_text(self.config.read_text().replace("Mifal Guide", "Mifal  Guide", 1))

    def checked(self, result, code=0):
        text = result.stdout + result.stderr
        self.assertEqual(result.returncode, code, text)
        self.assertNotIn(SECRET, text)
        return text

    def during_preview(self, script):
        """Run script while update shows its preview, after it planned."""
        hook = self.root / "during.sh"
        hook.write_text("#!/bin/bash\n" + script + "\n")
        hook.chmod(0o755)
        self.fake("git", f'if [ "$1 $2 $3" = "-C {self.clone} log" ]; then "{hook}"; fi\nexec /usr/bin/git "$@"')

    def test_a_same_revision_update_changes_nothing(self):
        before = snapshot(self.home)
        text = self.checked(self.update("--yes"))
        self.assertIn("up to date", text)
        self.assertEqual(snapshot(self.home), before)

    def test_a_newer_release_refreshes_a_clean_block_and_keeps_an_outside_edit(self):
        rest = self.edit_outside()
        self.new_release()
        self.checked(self.update("--yes"))
        written = self.config.read_text()
        self.assertTrue(written.endswith(rest))
        self.assertIn("version=9.9.9", written.splitlines()[0])
        self.assertTrue(self.parsed(self.workhome)["developer_instructions"].endswith("One more rule.\n"))
        self.assertEqual(self.backup.read_text(), CONFIG)

    def test_an_inside_edit_holds_update_and_reinstall_with_nothing_changed(self):
        self.edit_inside()
        self.new_release()
        before = snapshot(self.home)
        for run in (lambda: self.update("--yes"), lambda: self.install(*self.flags(), check=False)):
            text = self.checked(run(), 1)
            self.assertIn("~/.codex-work/config.toml: its Mifal developer_instructions block changed since install",
                          text)
            self.assertNotIn("--overwrite-edits", text)
            self.assertEqual(snapshot(self.home), before)

    def test_uninstall_removes_a_clean_block_keeps_outside_edits_and_the_link(self):
        rest = self.edit_outside()
        text = self.checked(self.mifal("uninstall"))
        self.assertIn("remove the Mifal developer_instructions key from ~/.codex-work/config.toml", text)
        self.assertEqual(self.config.read_text(), rest)
        self.assertFalse(self.backup.exists())
        self.assertEqual(os.readlink(self.workhome / "AGENTS.md"), str(self.shared))
        self.assertEqual(self.shared.read_text(), SHARED)

    def test_uninstall_restores_the_untouched_original_and_removes_a_config_it_created(self):
        self.install_c(self.personal)
        self.checked(self.mifal("uninstall"))
        self.assertEqual(self.config.read_text(), CONFIG)
        self.assertFalse((self.personal / "config.toml").exists())
        self.assertFalse((self.home / ".agents/mifal").exists())

    def test_uninstall_keeps_an_edited_block_and_its_backup(self):
        self.edit_inside()
        edited = self.config.read_bytes()
        text = self.checked(self.mifal("uninstall"))
        self.assertIn("kept the Mifal developer_instructions key in ~/.codex-work/config.toml: changed since install; "
                      "your copy from before install is ~/" + str(self.backup.relative_to(self.home)), text)
        self.assertEqual(self.config.read_bytes(), edited)
        self.assertEqual(self.backup.read_text(), CONFIG)

    def test_a_change_during_approval_stops_the_update(self):
        self.new_release()
        self.during_preview(f"printf 'x = 1\\n' >> '{self.config}'")
        result = self.run_in_terminal("/bin/bash", self.home / ".local/bin/mifal", "update", answer="y\n")
        text = self.checked(result, 1)
        self.assertIn("Your files changed while the update waited for approval", text)
        self.assertEqual(self.config.read_text(), self.keyed + "x = 1\n")

    def test_a_change_after_the_plan_under_yes_is_rolled_back_and_kept(self):
        self.new_release()
        self.during_preview(f"printf 'x = 1\\n' >> '{self.config}'")
        text = self.checked(self.update("--yes"), 1)
        self.assertIn("rolled back", text)
        self.assertEqual(self.config.read_text(), self.keyed + "x = 1\n")

    def test_a_failed_update_restores_the_config_byte_for_byte(self):
        self.new_release()
        before = snapshot(self.home)
        text = self.checked(self.update("--yes", MIFAL_TEST_FAIL_AT="before-publication"), 1)
        self.assertIn("rolled back", text)
        self.assertEqual(self.config.read_text(), self.keyed)
        self.assertEqual(snapshot(self.home), before)


class PendingLifecycle(Update, OptionC):
    def setUp(self):
        super().setUp()
        self.hook = self.personal / "hooks.json"
        self.hook.write_text(hooks("cat ~/.agents/mifal/AGENTS.md"))

    def status(self, root):
        return self.record(root)["status"]

    def test_pending_survives_a_reinstall_with_or_without_home(self):
        self.install_c(self.personal)
        for args in ((), self.flags(self.personal)):
            with self.subTest(args=args):
                result = self.install(*args)
                self.assertIn(f"pending codex: ~/.codex-personal: {REFERENCES}", result.stdout)
                self.assertEqual(self.status(self.personal), "pending")
                self.assertFalse((self.personal / "config.toml").exists())

    def test_removing_the_hook_then_a_same_revision_update_writes_the_key(self):
        self.install_c(self.personal)
        self.hook.unlink()
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.parsed(self.personal)["developer_instructions"], self.guide())
        self.assertEqual(self.status(self.personal), "wired")

    def test_a_pending_same_revision_update_says_so_and_writes_nothing(self):
        self.install_c(self.personal)
        before = snapshot(self.home)
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(f"pending codex: ~/.codex-personal: {REFERENCES}", result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_a_hook_added_beside_an_owned_key_holds_the_plan(self):
        self.install_c(self.workhome)
        (self.workhome / "hooks.json").write_text(hooks("cat ~/.agents/mifal/AGENTS.md"))
        before = snapshot(self.home)
        for run in (lambda: self.update("--yes"), lambda: self.install(check=False)):
            result = run()
            text = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, text)
            self.assertIn("~/.codex-work/config.toml: holds Mifal's developer_instructions key, but "
                          f"{REFERENCES}; remove that hook", text)
            self.assertEqual(snapshot(self.home), before)

    def test_an_unknown_home_stays_unknown_across_a_reinstall_and_an_update(self):
        self.hook.write_text("{")
        self.install_c(self.personal)
        for run in (lambda: self.install(), lambda: self.update("--yes")):
            result = run()
            self.assertIn("unknown codex: ~/.codex-personal: Mifal cannot classify", result.stdout)
            self.assertEqual(self.status(self.personal), "unknown")
            self.assertNotIn("Pending, not served", result.stdout)

    def test_a_hook_change_during_approval_stops_the_update(self):
        self.install_c(self.workhome, self.personal)
        self.publish("a new release", VERSION="9.9.9\n")
        hook = self.root / "during.sh"
        hook.write_text(f"#!/bin/bash\necho '{hooks('cat ~/.agents/mifal/AGENTS.md; true')}' > '{self.hook}'\n")
        hook.chmod(0o755)
        self.fake("git", f'if [ "$1 $2 $3" = "-C {self.clone} log" ]; then "{hook}"; fi\nexec /usr/bin/git "$@"')
        result = self.run_in_terminal("/bin/bash", self.home / ".local/bin/mifal", "update", answer="y\n")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Your files changed while the update waited for approval", result.stdout)
        self.assertEqual(self.manifest()["version"], "0.3.0")


class Doctor(OptionC):
    """Doctor claims the owned key's integrity only, and re-reads hooks.json for a pending Home."""

    def doctor(self):
        result = self.mifal("doctor", check=False)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        return [line for line in result.stdout.splitlines() if "guide codex" in line]

    def test_a_clean_key_passes_on_integrity_alone(self):
        (self.workhome / "config.toml").write_text(CONFIG)
        self.install_c()
        self.assertEqual(self.doctor(), ["PASS guide codex: Mifal's developer_instructions key in "
                                         "~/.codex-work/config.toml, as installed"])

    def test_an_edited_key_or_a_config_that_no_longer_parses_fails(self):
        config = self.workhome / "config.toml"
        config.write_text(CONFIG)
        self.install_c()
        keyed = config.read_text()
        for name, text, line in (
                ("edited", keyed.replace("Mifal Guide", "Mifal  Guide", 1),
                 "FAIL guide codex: the Mifal developer_instructions key in ~/.codex-work/config.toml is missing or "
                 "edited"),
                ("unparseable", keyed + f'model = "{SECRET}\n',
                 "FAIL guide codex: ~/.codex-work/config.toml is not UTF-8 TOML any more"),
                ("removed", None, "FAIL guide codex: ~/.codex-work/config.toml is missing")):
            with self.subTest(name=name):
                if text is None:
                    config.unlink()
                else:
                    config.write_text(text)
                self.assertEqual(self.doctor(), [line])

    def test_a_pending_home_warns_and_an_unreadable_hooks_file_fails(self):
        hook = self.personal / "hooks.json"
        hook.write_text(hooks("cat ~/.agents/mifal/AGENTS.md"))
        self.install_c(self.personal)
        self.assertEqual(self.doctor(), [f"WARN guide codex: ~/.codex-personal is pending: {REFERENCES}"])
        hook.write_text("{")
        self.assertEqual(self.doctor(), ["FAIL guide codex: ~/.codex-personal is unknown: Mifal cannot classify "
                                         "~/.codex-personal/hooks.json, so it adds no key"])
        hook.unlink()
        self.assertEqual(self.doctor(), ["WARN guide codex: ~/.codex-personal is pending, and nothing in its "
                                         "hooks stops the key now"])

    def test_a_hook_beside_a_clean_key_warns(self):
        self.install_c()
        (self.workhome / "hooks.json").write_text(hooks("cat ~/.agents/mifal/AGENTS.md"))
        self.assertEqual(self.doctor(), ["WARN guide codex: ~/.codex-work/hooks.json has a SessionStart hook beside "
                                         "Mifal's developer_instructions key in ~/.codex-work/config.toml"])


if __name__ == "__main__":
    unittest.main()
