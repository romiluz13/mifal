"""mifal update and mifal doctor serve the homes the install recorded, not the ones the shell's variables name."""

import json
import unittest

from support import MANIFEST, snapshot
from test_update import Update

NEW_SKILL = {"skills/newskill/SKILL.md": "---\nname: newskill\ndescription: x\n---\nBody\n"}


class Recorded(Update):
    """Claude is installed with CLAUDE_CONFIG_DIR at ~/.claude-alt; later commands run in a plain shell."""

    wire = ("claude",)

    def setUp(self):
        self.alt = None
        super().setUp()

    def install(self, *args, **kw):
        self.alt = self.home / ".claude-alt"
        self.alt.mkdir(exist_ok=True)
        self.harness_fakes(*self.wire)
        flags = [f for name in self.wire for f in ("--harness", name)]
        return super().install(*flags, *args, **{"CLAUDE_CONFIG_DIR": str(self.alt), **kw})

    def assert_served(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.alt / "skills/newskill").is_symlink())
        self.assertFalse((self.home / ".claude").exists())


class Serves(Recorded):
    def test_a_plain_shell_update_serves_the_recorded_home_and_prints_no_note(self):
        self.publish("add a skill", **NEW_SKILL)
        result = self.update("--yes")
        self.assert_served(result)
        self.assertNotIn("note", result.stdout)

    def test_a_variable_naming_another_home_is_noted_and_the_recorded_home_is_served(self):
        self.publish("add a skill", **NEW_SKILL)
        other = self.home / ".claude-other"
        other.mkdir()
        result = self.update("--yes", CLAUDE_CONFIG_DIR=str(other))
        self.assert_served(result)
        self.assertIn(
            "note CLAUDE_CONFIG_DIR is ~/.claude-other, but Mifal serves ~/.claude-alt; "
            "to serve another home, run ./install.sh",
            result.stdout,
        )
        self.assertEqual(list(other.iterdir()), [])

    def test_a_variable_naming_a_symlink_of_the_recorded_root_is_not_noted(self):
        self.publish("add a skill", **NEW_SKILL)
        (self.home / "via").symlink_to(self.alt)
        result = self.update("--yes", CLAUDE_CONFIG_DIR=str(self.home / "via"))
        self.assert_served(result)
        self.assertNotIn("note", result.stdout)

    def test_the_same_variable_as_at_install_is_not_noted(self):
        self.publish("add a skill", **NEW_SKILL)
        result = self.update("--yes", CLAUDE_CONFIG_DIR=str(self.alt))
        self.assert_served(result)
        self.assertNotIn("note", result.stdout)


class Skipped(Recorded):
    """Codex is detected at ~/.codex but its override file makes the install skip it."""

    wire = ("claude", "codex")

    def install(self, *args, **kw):
        codex = self.home / ".codex"
        codex.mkdir(exist_ok=True)
        (codex / "AGENTS.override.md").write_text("mine\n")
        return super().install(*args, **kw)

    def test_a_skipped_agent_whose_skip_no_longer_holds_is_wired_by_the_update(self):
        self.assertEqual(self.manifest()["harnesses"]["codex"][0]["status"], "skipped")
        self.publish("add a skill", **NEW_SKILL)
        (self.home / ".codex/AGENTS.override.md").unlink()
        result = self.update("--yes")
        self.assert_served(result)
        self.assertIn("block ~/.codex/AGENTS.md", result.stdout.splitlines())
        self.assertNotIn("not served", result.stdout)
        self.assertEqual((self.home / ".codex/AGENTS.md").read_text().count("<!-- mifal:begin "), 1)
        self.assertEqual(self.manifest()["harnesses"]["codex"][0]["status"], "wired")


class Absent(Recorded):
    def test_a_detected_agent_that_is_not_in_the_record_is_noted_and_not_wired(self):
        self.harness_fakes("codex")
        self.publish("add a skill", **NEW_SKILL)
        result = self.update("--yes")
        self.assert_served(result)
        self.assertIn("found codex at ~/.codex, not served; run ./install.sh to add it", result.stdout)
        self.assertFalse((self.home / ".codex").exists())
        self.assertNotIn("codex", self.manifest()["harnesses"])


class Doctor(Recorded):
    def test_doctor_after_a_plain_shell_update_checks_the_recorded_root(self):
        self.publish("add a skill", **NEW_SKILL)
        self.assert_served(self.update("--yes"))
        result = self.mifal("doctor", check=False)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertRegex(result.stdout, r"(?m)^PASS skills claude: \d+ links in ~/\.claude-alt/skills")
        self.assertEqual([l for l in result.stdout.splitlines() if l.startswith("FAIL")], [])
        self.assertFalse((self.home / ".claude").exists())
        self.assertNotIn("note", result.stdout)

    def test_doctor_notes_a_variable_that_names_another_home(self):
        other = self.home / ".claude-other"
        other.mkdir()
        result = self.mifal("doctor", check=False, CLAUDE_CONFIG_DIR=str(other))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("note CLAUDE_CONFIG_DIR is ~/.claude-other, but Mifal serves ~/.claude-alt", result.stdout)


class NoRecord(Recorded):
    def test_a_manifest_without_a_harness_record_takes_the_shells_environment_as_before(self):
        path = self.home / MANIFEST
        data = json.loads(path.read_text())
        del data["harnesses"]
        path.write_text(json.dumps(data))
        self.publish("add a skill", **NEW_SKILL)
        result = self.update("--yes", CLAUDE_CONFIG_DIR=str(self.alt))
        self.assert_served(result)
        self.assertNotIn("note", result.stdout)


class Advice(Recorded):
    def test_a_stop_alone_does_not_offer_overwrite_edits(self):
        self.publish("add a skill", **NEW_SKILL)
        (self.home / "agents-real").mkdir()
        (self.home / ".agents").rename(self.home / "agents-real/agents")
        (self.home / ".agents").symlink_to("agents-real/agents")
        before = snapshot(self.home)
        result = self.update("--yes")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("now resolves to", result.stdout)
        self.assertIn("Nothing was changed.", result.stdout)
        self.assertNotIn("--overwrite-edits", result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_a_conflict_offers_overwrite_edits(self):
        self.publish("add a skill", **NEW_SKILL)
        (self.home / ".agents/skills/grilling/SKILL.md").write_text("edited\n")
        result = self.update("--yes")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("changed since Mifal wrote it", result.stdout)
        self.assertIn("mifal update --overwrite-edits", result.stdout)


class ZeroTwo(Recorded):
    """A Manifest as Mifal 0.2.x wrote it: one record and one folder record per Harness."""

    wire = ("claude", "codex")

    def write_0_2(self):
        alt, codex = str(self.alt), str(self.home / ".codex")
        self.homes = {"claude": {"root": alt, "rules": alt + "/CLAUDE.md", "status": "wired"},
                      "codex": {"root": codex, "rules": codex + "/AGENTS.md", "status": "wired"}}
        data = self.manifest()
        data["harnesses"] = self.homes
        data["folders"] = {k: f for k, f in data["folders"].items() if not k.startswith("harness:")}
        data["folders"].update({"harness:claude": {"path": alt, "real": alt}, "harness:codex": {"path": codex, "real": codex}})
        (self.home / MANIFEST).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    def test_an_update_reads_each_record_as_a_one_home_list_and_writes_the_new_shape(self):
        self.write_0_2()
        self.publish("add a skill", **NEW_SKILL)
        self.assert_served(self.update("--yes"))
        data = self.manifest()
        self.assertEqual(data["harnesses"], {name: [rec] for name, rec in self.homes.items()})
        self.assertEqual({k: f for k, f in data["folders"].items() if k.startswith("harness:")},
                         {f"harness:{name}:{rec['root']}": {"path": rec["root"], "real": rec["root"]}
                          for name, rec in self.homes.items()})

    def test_an_install_writes_the_new_shape_back_even_with_nothing_else_to_change(self):
        self.write_0_2()
        result = self.install()
        self.assertIn("update ~/.agents/mifal/install-manifest.json", result.stdout.splitlines())
        self.assertEqual(self.manifest()["harnesses"], {name: [rec] for name, rec in self.homes.items()})

    def test_uninstall_reads_the_migrated_folder_records(self):
        self.write_0_2()
        moved = self.home / "moved-claude"
        self.alt.rename(moved)
        self.alt.symlink_to(moved)
        before = snapshot(self.home)
        result = self.mifal("uninstall", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("~/.claude-alt now resolves to ~/moved-claude", result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_a_manifest_that_cannot_be_read_stops_the_update_with_nothing_written(self):
        data = self.manifest()
        data["harnesses"] = {"claude": "not a home"}
        (self.home / MANIFEST).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        self.publish("add a skill", **NEW_SKILL)
        before, head = snapshot(self.home), self.head()
        result = self.update("--yes")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("mifal: the Manifest at ~/.agents/mifal/install-manifest.json cannot be read: harness claude "
                      "has no usable home record. Nothing was changed.", result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(self.head(), head)


if __name__ == "__main__":
    unittest.main()
