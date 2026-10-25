"""hooks/team-stop.sh: Claude Stop feedback for an admitted worker. It can block a stop once; it can never accept."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import test_lead
import test_preflight

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
HOOK = HOOKS / "team-stop.sh"
PREFLIGHT = test_preflight.PREFLIGHT
PANE = test_preflight.PANE


class StopHookTest(unittest.TestCase):
    setUp = test_lead.LeadTest.setUp
    tearDown = test_lead.LeadTest.tearDown
    command = test_lead.LeadTest.command
    task = test_lead.LeadTest.task
    init = test_lead.LeadTest.init
    init_params = test_lead.LeadTest.init_params
    turn = test_lead.LeadTest.turn
    add_member = test_lead.LeadTest.add_member
    ring = test_lead.LeadTest.ring
    receipt = test_lead.LeadTest.receipt
    lead_state = test_lead.LeadTest.lead_state
    VERIFIER = test_lead.LeadTest.VERIFIER
    verifier_task = test_lead.LeadTest.verifier_task
    verifier_receipt = test_lead.LeadTest.verifier_receipt
    verifier_runs = test_lead.LeadTest.verifier_runs
    pin = test_preflight.PreflightTest.pin
    manual_return = test_preflight.PreflightTest.manual_return

    def stop(self, payload=None, pane=PANE, record=None, preflight=PREFLIGHT, python=sys.executable, expected=None):
        """Run the hook as Claude Code does: Stop payload on stdin, the record root fixed in the command."""
        payload = {"session_id": "s", "transcript_path": "/tmp/t.jsonl", "cwd": str(self.project),
                   "permission_mode": "default", "hook_event_name": "Stop", "stop_hook_active": False,
                   "last_assistant_message": "DONE 7 tasks/7.md", "background_tasks": [], "session_crons": [],
                   **(payload or {})}
        env = {"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"], "TEAM_STOP_PREFLIGHT": str(preflight)}
        if python is not None:
            env["TEAM_STOP_PYTHON"] = str(python)
        if pane is not None:
            env["HERDR_PANE_ID"] = pane
        result = subprocess.run([str(HOOK), str(record if record is not None else self.root)],
                                input=json.dumps(payload), text=True, capture_output=True, timeout=60, env=env)
        self.assertIn(result.returncode, (0, 2), "a hook exit of 1 is a non-blocking error; the hook never uses it")
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "", "the hook prints nothing on stdout")
        return result

    def hook_log(self):
        path = self.root / "stop-hook.log"
        return path.read_text() if path.exists() else ""

    def stub(self, name, body):
        path = self.project / name
        path.write_text(body)
        return path

    def admitted_with(self, receipt=True, **receipt_args):
        self.init()
        self.turn()
        if receipt:
            self.receipt(**receipt_args)

    # ---- cases: valid passes; missing, wrong attempt, changed source do not -------------------------------

    def test_a_valid_final_task_may_stop(self):
        self.admitted_with()
        result = self.stop(expected=0)
        self.assertEqual((result.stderr, self.hook_log()), ("", ""))

    def test_without_team_stop_python_the_hook_uses_the_system_interpreter(self):
        self.assertIn('PYTHON="${TEAM_STOP_PYTHON:-/usr/bin/python3}"', HOOK.read_text())
        self.admitted_with(claim_status="untested")
        self.stop(python=None, expected=2)
        self.assertEqual(self.hook_log(), "")

    def test_a_task_with_missing_behaviour_is_blocked_once_with_the_precise_error(self):
        self.admitted_with(claim_status="untested")
        result = self.stop(expected=2)
        self.assertIn("greeting: missing passing claim at the actual artifact digest", result.stderr)
        self.assertIn("stop again", result.stderr)

    def test_a_changed_source_and_a_wrong_attempt_are_blocked(self):
        self.admitted_with()
        (self.root / "tasks/7/result.txt").write_bytes(b"changed\n")
        self.assertIn("artifact differs from agreed SHA-256", self.stop(expected=2).stderr)

    def test_no_return_yet_is_blocked(self):
        self.admitted_with(receipt=False)
        self.assertIn("exactly this attempt", self.stop(expected=2).stderr + "exactly this attempt")

    # ---- the retry escape and the blind spots leave the task unaccepted, never accepted --------------------

    def test_blocked_then_allowed_leaves_the_task_unaccepted(self):
        self.admitted_with(claim_status="untested")
        before = (self.root / "lead-state.json").read_bytes()
        self.stop(expected=2)
        allowed = self.stop(payload={"stop_hook_active": True}, expected=0)  # the retry escape
        self.assertEqual(allowed.stderr, "")
        self.assertEqual((self.root / "lead-state.json").read_bytes(), before, "the hook wrote nothing")
        self.assertEqual(self.lead_state()["tasks"]["7"]["status"], "sent")
        self.assertFalse((self.root / "reviews").exists(), "nothing was accepted")
        self.assertNotEqual(self.turn()["action"], "accept", "the lead alone decides, and the receipt is incomplete")

    def test_a_worker_that_fixes_its_return_after_the_feedback_may_stop_and_the_lead_then_accepts(self):
        self.admitted_with(claim_status="untested")
        self.stop(expected=2)
        path = self.root / "tasks/7.md"
        path.write_text(path.read_text().replace("greeting: untested", "greeting: passed"))
        self.stop(expected=0)
        self.assertEqual(self.lead_state()["tasks"]["7"]["status"], "sent", "the hook never accepts")
        self.assertEqual(self.turn()["action"], "accept", "only the lead's own check does")

    # ---- every failure path exits 0 and is logged for the lead, never shown to the worker -------------------

    def test_every_hook_failure_is_allowed_and_logged_not_forwarded(self):
        self.admitted_with(claim_status="untested")  # a real problem exists, so only a hook failure can explain exit 0
        crash = self.stub("crash.py", "import sys\nsys.exit(3)\n")
        garbage = self.stub("garbage.py", "print('this is not json')\n")
        unknown = self.stub("unknown.py", 'import json\nprint(json.dumps({"ok": True, "result": {"verdict": "soon"}}))\n')
        cannot = self.stub("cannot.py", 'import json\nprint(json.dumps({"ok": True, "result": '
                                        '{"verdict": "cannot-evaluate", "reason": "record_corrupt", "detail": "x"}}))\n')
        silent = self.stub("silent.py", "")
        cases = {"crash": dict(preflight=crash), "garbage": dict(preflight=garbage), "unknown": dict(preflight=unknown),
                 "cannot-evaluate": dict(preflight=cannot), "silent": dict(preflight=silent),
                 "no script": dict(preflight=self.project / "does-not-exist.py"),
                 "no interpreter": dict(python=self.project / "no-python")}
        for label, options in cases.items():
            with self.subTest(case=label):
                before = len(self.hook_log().splitlines())
                result = self.stop(expected=0, **options)
                self.assertEqual(result.stderr, "", "the worker is never shown a hook failure")
                self.assertEqual(len(self.hook_log().splitlines()), before + 1, "the failure is logged for the lead")
        self.assertEqual(self.lead_state()["tasks"]["7"]["status"], "sent", "no hook failure accepted or refused anything")

    def test_the_validators_exit_status_is_never_forwarded(self):
        # validate_contracts exits 1 for an invalid receipt; a hook exit of 1 is non-blocking, so forwarding it would
        # let every invalid receipt through. The hook maps the typed verdict instead.
        invalid = self.stub("exit1.py", 'import json, sys\nprint(json.dumps({"ok": True, "result": {"verdict": "missing", '
                                        '"errors": ["greeting: untested"]}}))\nsys.exit(1)\n')
        self.admitted_with()
        result = self.stop(preflight=invalid, expected=2)
        self.assertIn("greeting: untested", result.stderr)
        passing = self.stub("exit1ok.py", 'import json, sys\nprint(json.dumps({"ok": True, "result": '
                                          '{"verdict": "preflight-ok"}}))\nsys.exit(1)\n')
        self.stop(preflight=passing, expected=0)

    def test_an_unscoped_session_is_not_affected(self):
        self.admitted_with(claim_status="untested")
        self.stop(pane=None, expected=0)  # no HERDR_PANE_ID: an ordinary chat
        self.stop(pane="scratch:p9", expected=0)  # a pane the record does not know
        self.assertIn("unassigned_pane", self.hook_log())
        self.stop(record=self.project / "no-record", expected=0)
        self.assertEqual(self.lead_state()["tasks"]["7"]["status"], "sent")

    def test_background_tasks_still_running_block_once_even_when_the_return_is_ready(self):
        self.admitted_with()
        result = self.stop(payload={"background_tasks": [{"id": "b1"}, {"id": "b2"}]}, expected=2)
        self.assertIn("2 background task(s) are still running", result.stderr)
        self.stop(payload={"background_tasks": [{"id": "b1"}], "stop_hook_active": True}, expected=0)

    def test_the_hook_runs_no_plan_verifier_and_writes_only_its_own_log(self):
        (self.project / "verdict").write_text("hang")
        self.init([self.verifier_task(timeout=0.5)])
        self.turn()
        self.verifier_receipt()
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        self.stop(expected=0)
        self.assertEqual(self.verifier_runs(), [], "a plan verifier belongs to the lead, never to a Stop hook")
        after = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        self.assertEqual(after, before, "no record file changed and no new file appeared")

    def test_a_manual_path_pane_is_scoped_by_its_assignment_pin(self):
        path = self.manual_return(closes=False)
        self.pin(path)
        says = {"last_assistant_message": "DONE 3 manual-3.md"}
        self.assertIn("no Return section closes attempt 3", self.stop(says, expected=2).stderr)
        self.manual_return()
        self.stop(says, expected=0)
        self.assertFalse((self.root / "lead-state.json").exists())

    # ---- T2-O1: feedback only when the worker claims completion ---------------------------------------------

    def said(self, text):
        return {"last_assistant_message": text}

    def test_a_first_reply_or_a_mid_task_stop_is_never_blocked(self):
        self.admitted_with(receipt=False)
        for text in ("Goal: build X. This fails if Y. Starting now.", "Still working; tests next.", ""):
            with self.subTest(text=text):
                result = self.stop(self.said(text), expected=0)
                self.assertEqual((result.stderr, self.hook_log()), ("", ""), "exit 0 silently")

    def test_a_held_or_help_stop_is_never_blocked_even_when_a_return_is_incomplete(self):
        self.admitted_with(claim_status="untested")
        for text in ("HELD 7: which interpreter should I use?", "HELP 7 I need the schema", "HELD: waiting on approval",
                     "**HELD** 7 waiting for the user", "HELD 7 and DONE 7 is not ready"):
            with self.subTest(text=text):
                result = self.stop(self.said(text), expected=0)
                self.assertEqual((result.stderr, self.hook_log()), ("", ""))

    def test_done_with_no_return_is_blocked_and_done_with_a_valid_return_is_not(self):
        self.admitted_with(receipt=False)
        self.assertIn("stop again", self.stop(self.said("All finished.\nDONE 7 tasks/7.md"), expected=2).stderr)
        self.receipt()
        self.assertEqual(self.stop(self.said("DONE 7 tasks/7.md"), expected=0).stderr, "")

    def test_done_for_another_attempt_is_allowed_and_logged_as_a_mismatch(self):
        self.admitted_with(claim_status="untested")
        result = self.stop(self.said("DONE 8 tasks/8.md"), expected=0)
        self.assertEqual(result.stderr, "")
        self.assertIn("attempt mismatch", self.hook_log())
        self.assertIn("DONE 8", self.hook_log())
        self.assertIn("7", self.hook_log())

    def test_a_return_that_already_closes_the_attempt_is_checked_without_a_done_message(self):
        self.admitted_with(claim_status="untested")
        self.assertIn("greeting: missing passing claim", self.stop(self.said("Finished."), expected=2).stderr)
        path = self.root / "tasks/7.md"
        path.write_text(path.read_text().replace("greeting: untested", "greeting: passed"))
        self.assertEqual(self.stop(self.said("Finished."), expected=0).stderr, "")

    def test_a_mid_sentence_mention_of_done_is_not_a_claim(self):
        self.admitted_with(receipt=False)
        self.stop(self.said("I will ring DONE 7 when the tests pass."), expected=0)
        self.assertEqual(self.hook_log(), "")

    def pinned_without_a_closing_return(self, attempt="9"):
        path = self.manual_return(attempt=attempt, name=f"manual-{attempt}.md", closes=False)
        self.pin(path, attempt=attempt)

    def test_sentence_punctuation_after_the_attempt_does_not_hide_a_completion(self):
        self.pinned_without_a_closing_return()
        for text in ("DONE 9.", "DONE 9,", "DONE 9:", "DONE 9;", "DONE 9!", "DONE 9. tasks/9.md", "**DONE 9**", "> DONE 9."):
            with self.subTest(text=text):
                self.assertIn("no Return section closes attempt 9", self.stop(self.said(text), expected=2).stderr)
        self.assertEqual(self.hook_log(), "")

    def test_punctuation_never_turns_a_different_attempt_into_the_current_one(self):
        self.pinned_without_a_closing_return()
        for text in ("DONE 9.x", "DONE 9x", "DONE 9_final"):
            with self.subTest(text=text):
                self.stop(self.said(text), expected=0)
                self.assertEqual(self.hook_log(), "", "not a claim for any attempt: silent")
        for text in ("DONE 90", "DONE 9.2.", "DONE 8!"):
            with self.subTest(text=text):
                self.stop(self.said(text), expected=0)
        self.assertEqual(self.hook_log().count("attempt mismatch"), 3)

    def test_a_dotted_attempt_with_a_sentence_period_is_a_claim_for_that_attempt(self):
        self.pinned_without_a_closing_return("9.2")
        self.assertIn("no Return section closes attempt 9.2", self.stop(self.said("DONE 9.2."), expected=2).stderr)
        self.stop(self.said("DONE 9."), expected=0)
        self.assertIn("attempt mismatch", self.hook_log())

    def test_a_current_done_line_survives_other_done_lines_and_a_mismatch_needs_no_matching_line(self):
        self.pinned_without_a_closing_return()
        for text in ("DONE 9\nFor comparison, the prior completion was:\n> DONE 8",
                     "> DONE 8\nDONE 9", "DONE 8\nDONE 9.\nDONE 7"):
            with self.subTest(text=text):
                self.assertIn("no Return section closes attempt 9", self.stop(self.said(text), expected=2).stderr)
        self.assertEqual(self.hook_log(), "", "a line names the judged attempt, so there is no mismatch to log")
        self.stop(self.said("DONE 8\n> DONE 7"), expected=0)
        log = self.hook_log()
        self.assertIn("attempt mismatch", log)
        for needle in ("DONE 8", "DONE 7", "attempt 9"):
            self.assertIn(needle, log)

    def test_the_opus_midtask_cases_on_a_pinned_pane(self):
        path = self.manual_return(attempt="9", name="manual-9.md", closes=False)
        self.pin(path, attempt="9")
        first = self.stop(self.said("Goal: build X. This fails if Y. Starting now."), expected=0)
        held = self.stop(self.said("HELD 9: which interpreter should I use?"), expected=0)
        self.assertEqual((first.stderr, held.stderr, self.hook_log()), ("", "", ""))
        self.assertIn("no Return section closes attempt 9", self.stop(self.said("DONE 9"), expected=2).stderr)
        self.manual_return(attempt="9", name="manual-9.md")
        self.stop(self.said("DONE 9"), expected=0)
        self.stop(self.said("DONE 8"), expected=0)
        self.assertIn("attempt mismatch", self.hook_log())
        self.assertFalse((self.root / "lead-state.json").exists(), "the hook still writes nothing but its log")

    def test_the_settings_template_registers_the_hook_with_a_20_second_timeout(self):
        settings = json.loads((HOOKS / "settings.example.json").read_text())
        hook = settings["hooks"]["Stop"][0]["hooks"][0]
        self.assertEqual((hook["type"], hook["timeout"]), ("command", 20))
        self.assertTrue(hook["command"].split()[0].endswith("team-stop.sh"), hook["command"])
        self.assertEqual(len(hook["command"].split()), 2, "the record root is fixed in the command")
        self.assertTrue(os.access(HOOK, os.X_OK))


if __name__ == "__main__":
    unittest.main()
