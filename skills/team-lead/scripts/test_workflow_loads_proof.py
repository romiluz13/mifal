"""A worker's `Loaded:` lines checked against the harness's own session log, through the public validator CLI."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_workflow_contracts import SCRIPT

START = "2026-10-17T10:00:00Z"


class LoadsProofTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.skill = self.root / "skills" / "kit" / "SKILL.md"
        self.skill.parent.mkdir(parents=True)
        self.skill.write_text("# Kit\nUse the kit.\n")
        self.guide = self.root / "guide.md"
        self.guide.write_text("# Guide\none\ntwo\n")
        self.rows, self.count = [], 0
        self.prompt("2026-10-17T09:50:00.000Z")

    def prompt(self, at, text=None, cwd=None):
        self.rows.append({"type": "user", "timestamp": at, "cwd": str(cwd or self.root / "elsewhere"),
                          "message": {"content": text or f"Task 3: read {self.root / 'task.md'} and start."}})

    def compaction(self, at):
        self.rows.append({"type": "system", "subtype": "compact_boundary", "timestamp": at})

    def brief(self, kit_at="2026-10-17T09:59:00Z"):
        return ("---\ntask: 3\nowner: worker\nlatitude: do-tell\nreturn: task.md\n---\n# Task 3\n"
                f"## Workflow\nProcedure: {self.skill}\nProcedure: {self.guide}\n"
                f"Check: start implement | passed | brief exit 0 at:{START}\n"
                "\n## Return\nCloses: 3\n### Result\nDone.\n### Claims\n- built: passed\n### Evidence\n"
                f"Loaded: {self.skill} | worker: sha256:{'a' * 64} Skill tool at:{kit_at}\n"
                f"Loaded: {self.guide} | worker: sha256:{'b' * 64} Read tool at:2026-10-17T09:59:30Z\n")

    def call(self, name, at, result_row, sidechain=False):
        self.count += 1
        uid = f"toolu_{self.count}"
        self.rows.append({"type": "assistant", "timestamp": at, "isSidechain": sidechain,
                          "message": {"content": [{"type": "tool_use", "id": uid, "name": name, "input": {}}]}})
        row = result_row(uid)
        row.setdefault("isSidechain", sidechain)
        self.rows.append(row)

    def skill_call(self, at, sidechain=False):
        text = f"Base directory for this skill: {self.skill.parent}\n\n# Kit\nUse the kit.\n"
        self.call("Skill", at, lambda uid: {"type": "user", "isMeta": True, "sourceToolUseID": uid, "timestamp": at,
                                            "message": {"content": [{"type": "text", "text": text}]}}, sidechain)

    def read_call(self, at, lines=(1, 3, 3)):
        start, num, total = lines
        self.call("Read", at, lambda uid: {
            "type": "user", "timestamp": at,
            "toolUseResult": {"type": "text", "file": {"filePath": str(self.guide), "startLine": start,
                                                       "numLines": num, "totalLines": total}},
            "message": {"content": [{"type": "tool_result", "tool_use_id": uid, "content": "1\t# Guide"}]}})

    def bash_call(self, at, output):
        self.call("Bash", at, lambda uid: {
            "type": "user", "timestamp": at,
            "message": {"content": [{"type": "tool_result", "tool_use_id": uid, "content": output}]}})

    def run_proof(self, brief, log=None, session_log=None):
        task = self.root / "task.md"
        task.write_text(brief)
        if session_log is None:
            session_log = self.root / "session.jsonl"
            session_log.write_text(log if log is not None else "\n".join(json.dumps(r) for r in self.rows) + "\n")
        return subprocess.run([sys.executable, "-B", str(SCRIPT), "loads-proof", str(task), "--log", str(session_log)],
                              capture_output=True, text=True, timeout=30)

    def proven_loads(self):
        self.skill_call("2026-10-17T09:58:10.100Z")
        self.read_call("2026-10-17T09:59:20.000Z")

    def test_skill_and_complete_read_before_the_work_are_proven(self):
        self.skill_call("2026-10-17T09:58:10.100Z")
        self.read_call("2026-10-17T09:59:20.000Z")
        result = self.run_proof(self.brief())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"proven: {self.skill.resolve()} by Skill at 2026-10-17T09:58:10Z", result.stdout)

    def test_a_body_the_log_never_loaded_is_refused(self):
        self.read_call("2026-10-17T09:59:20.000Z")
        result = self.run_proof(self.brief())
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("records no complete load", result.stderr)

    def test_a_partial_read_is_not_a_load(self):
        self.skill_call("2026-10-17T09:58:10.100Z")
        self.read_call("2026-10-17T09:59:20.000Z", lines=(1, 2, 3))
        self.assertEqual(self.run_proof(self.brief()).returncode, 1)

    def test_a_subagents_load_is_not_the_workers(self):
        self.skill_call("2026-10-17T09:58:10.100Z", sidechain=True)
        self.read_call("2026-10-17T09:59:20.000Z")
        self.assertEqual(self.run_proof(self.brief()).returncode, 1)

    def test_a_load_after_the_start_check_is_refused(self):
        self.skill_call("2026-10-17T10:05:00.000Z")
        self.read_call("2026-10-17T09:59:20.000Z")
        result = self.run_proof(self.brief(kit_at="2026-10-17T10:05:00Z"))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("after the work began", result.stderr)

    def test_a_claimed_time_before_the_logged_load_is_refused(self):
        self.skill_call("2026-10-17T09:59:10.000Z")
        self.read_call("2026-10-17T09:59:20.000Z")
        result = self.run_proof(self.brief(kit_at="2026-10-17T09:58:00Z"))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("the stamp was not taken from the read", result.stderr)

    def test_a_minute_stamp_covers_its_whole_minute(self):
        self.skill_call("2026-10-17T09:58:40.000Z")
        self.read_call("2026-10-17T09:59:20.000Z")
        self.assertEqual(self.run_proof(self.brief(kit_at="2026-10-17T09:58Z")).returncode, 0)

    def footer(self, digest):
        return f"# Guide\n-- end of body {self.guide} | sha256:{digest} bytes:17 --\n"

    def test_the_read_command_footer_is_a_load(self):
        self.skill_call("2026-10-17T09:58:10.100Z")
        self.bash_call("2026-10-17T09:59:20.000Z", self.footer(hashlib.sha256(self.guide.read_bytes()).hexdigest()))
        self.assertEqual(self.run_proof(self.brief()).returncode, 0)

    def test_a_footer_for_another_version_of_the_body_is_not_a_load(self):
        self.skill_call("2026-10-17T09:58:10.100Z")
        self.bash_call("2026-10-17T09:59:20.000Z", self.footer("c" * 64))
        self.assertEqual(self.run_proof(self.brief()).returncode, 1)

    def test_shell_output_holding_the_whole_body_is_a_load(self):
        self.skill_call("2026-10-17T09:58:10.100Z")
        self.bash_call("2026-10-17T09:59:20.000Z", "# Guide\none\ntwo\n")
        self.assertEqual(self.run_proof(self.brief()).returncode, 0)

    def test_shell_output_with_part_of_the_body_is_not(self):
        self.skill_call("2026-10-17T09:58:10.100Z")
        self.bash_call("2026-10-17T09:59:20.000Z", "# Guide\none\n")
        self.assertEqual(self.run_proof(self.brief()).returncode, 1)

    def test_a_log_that_never_received_the_brief_is_refused(self):
        self.rows = []
        self.prompt("2026-10-17T09:50:00.000Z", "Task 9: read nine.md and start.")
        self.skill_call("2026-10-17T09:58:10.100Z")
        self.read_call("2026-10-17T09:59:20.000Z")
        result = self.run_proof(self.brief())
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("never received task.md", result.stderr)

    def test_a_brief_named_only_after_the_work_began_does_not_bind_the_log(self):
        self.rows = []
        self.prompt("2026-10-17T10:30:00.000Z", f"DONE 3 {self.root / 'task.md'}")
        self.skill_call("2026-10-17T09:58:10.100Z")
        self.read_call("2026-10-17T09:59:20.000Z")
        self.assertEqual(self.run_proof(self.brief()).returncode, 1)

    def test_a_prompt_naming_another_file_that_ends_in_the_briefs_name_does_not_bind_the_log(self):
        for other in (self.root / "subtask.md", self.root / "other" / "task.md"):
            with self.subTest(other=other):
                self.rows = []
                self.prompt("2026-10-17T09:50:00.000Z", f"Task 9: read {other} and start.")
                self.proven_loads()
                result = self.run_proof(self.brief())
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("never received task.md", result.stderr)

    def test_a_relative_path_binds_the_log_from_the_prompts_folder(self):
        self.rows = []
        self.prompt("2026-10-17T09:50:00.000Z", "Task 3: read task.md and start.", cwd=self.root)
        self.proven_loads()
        self.assertEqual(self.run_proof(self.brief()).returncode, 0)

    def test_a_brief_with_no_stamped_start_check_cannot_be_proven(self):
        self.proven_loads()
        result = self.run_proof(self.brief().replace(f" at:{START}", ""))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("no stamped start Check", result.stderr)

    def test_a_loaded_line_with_an_unreadable_time_is_refused(self):
        self.proven_loads()
        result = self.run_proof(self.brief(kit_at="2026-10-17 09:59"))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("no readable at: time", result.stderr)

    def test_a_log_that_is_not_a_regular_file_is_an_input_error(self):
        fifo = self.root / "session.fifo"
        os.mkfifo(fifo)
        result = self.run_proof(self.brief(), session_log=fifo)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("not a regular file", result.stderr)

    def test_a_brief_that_selects_no_body_cannot_be_proven(self):
        self.proven_loads()
        brief = self.brief().replace(f"Procedure: {self.skill}\nProcedure: {self.guide}\n", "")
        result = self.run_proof(brief)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("selects no body", result.stderr)

    def test_a_loaded_time_from_a_load_before_a_compaction_stands_when_the_body_was_reloaded(self):
        self.skill_call("2026-10-17T09:30:00.000Z")
        self.compaction("2026-10-17T09:40:00.000Z")
        self.proven_loads()
        self.assertEqual(self.run_proof(self.brief(kit_at="2026-10-17T09:30:00Z")).returncode, 0)

    def test_a_load_before_the_last_compaction_is_out_of_context(self):
        self.skill_call("2026-10-17T09:58:10.100Z")
        self.read_call("2026-10-17T09:59:20.000Z")
        self.compaction("2026-10-17T09:59:40.000Z")
        result = self.run_proof(self.brief())
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("compaction", result.stderr)

    def test_a_reload_after_the_compaction_counts(self):
        self.skill_call("2026-10-17T09:30:00.000Z")
        self.compaction("2026-10-17T09:40:00.000Z")
        self.skill_call("2026-10-17T09:58:10.100Z")
        self.read_call("2026-10-17T09:59:20.000Z")
        self.assertEqual(self.run_proof(self.brief()).returncode, 0)

    def test_a_log_that_is_not_a_claude_code_session_is_an_input_error(self):
        result = self.run_proof(self.brief(), log='{"note": "not a session"}\n')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("not a Claude Code session log", result.stderr)


if __name__ == "__main__":
    unittest.main()
