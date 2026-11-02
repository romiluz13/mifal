"""preflight.py: a read-only look at a worker's return before it stops. Feedback only; the lead still accepts."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

import test_lead

PREFLIGHT = Path(__file__).resolve().parents[1] / "preflight.py"
ADAPTER = PREFLIGHT.parent
OK, MISSING, CANNOT = "preflight-ok", "missing", "cannot-evaluate"
PANE = "scratch:p1"


def run_preflight(params, expected=0):
    result = subprocess.run([sys.executable, "-B", str(PREFLIGHT)],
                            input=json.dumps({"command": "preflight", "params": params}),
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == expected, (result.returncode, result.stdout, result.stderr[-400:])
    response = json.loads(result.stdout)
    return response["result"] if expected == 0 else response


def tree(root):
    """Every file under the record, by relative path, with its digest: the evidence that nothing was written."""
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


class PreflightTest(unittest.TestCase):
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

    def preflight(self, pane=PANE, expected=0, **params):
        return run_preflight({"record_root": str(self.root), "pane_id": pane, **params}, expected)

    def triple(self, path, attempt, matt=False, expected=0):
        return run_preflight({"return": str(path), "attempt": attempt, "matt": matt}, expected)

    # ---- the lead-record path: the one claim evaluator, never a second one ----------------------------

    def test_a_valid_final_task_is_preflight_ok(self):
        self.init()
        self.turn()
        self.receipt()
        verdict = self.preflight()
        self.assertEqual((verdict["verdict"], verdict["source"], verdict["task"], verdict["attempt"]),
                         (OK, "lead-record", "7", "7"), verdict)

    def test_missing_behaviour_is_missing_with_the_precise_claim(self):
        self.init()
        self.turn()
        self.receipt(claim_status="untested")
        verdict = self.preflight()
        self.assertEqual(verdict["verdict"], MISSING, verdict)
        self.assertEqual(verdict["errors"], ["greeting: missing passing claim at the actual artifact digest"])

    def test_no_receipt_yet_is_missing_not_an_error(self):
        self.init()
        self.turn()
        verdict = self.preflight()
        self.assertEqual(verdict["verdict"], MISSING, verdict)
        self.assertTrue(any("close" in e or "Return" in e for e in verdict["errors"]), verdict)

    def test_a_changed_source_after_the_claim_is_missing(self):
        self.init()
        self.turn()
        path = self.receipt()
        (self.root / "tasks/7/result.txt").write_bytes(b"changed after the claim\n")
        verdict = self.preflight()
        self.assertEqual(verdict["verdict"], MISSING, verdict)
        self.assertIn("greeting: artifact differs from agreed SHA-256", verdict["errors"])
        self.assertTrue(path.exists())

    def test_a_wrong_attempt_is_missing(self):
        self.init()
        self.turn()
        self.receipt(content=b"wrong\n")
        self.ring("DONE 7 tasks/7.md")
        self.assertEqual(self.turn()["action"], "correct")
        self.assertEqual(self.turn()["task"], "7.2")
        stale = self.root / "tasks/7.2.md"
        with stale.open("a") as stream:  # a return that closes the old attempt, not the active one
            stream.write("\n## Return — attempt 7\n\nCloses: 7\n\n### Result\nx\n\n### Claims\n"
                         "- greeting: passed (sha256 " + hashlib.sha256(b"hello\n").hexdigest() + ")\n\n"
                         "### Evidence\nx\n\n### Sidecars\n- tasks/7/result.txt\n")
        verdict = self.preflight()
        self.assertEqual(verdict["verdict"], MISSING, verdict)
        self.assertTrue(any("exactly this attempt" in e for e in verdict["errors"]), verdict)
        self.assertEqual(self.lead_state()["tasks"]["7"]["active"], "7.2")

    def test_a_changed_brief_prefix_is_missing(self):
        self.init()
        self.turn()
        path = self.receipt()
        path.write_text(path.read_text().replace("## Why", "## Why (edited by the worker)", 1))
        verdict = self.preflight()
        self.assertEqual(verdict["verdict"], MISSING, verdict)
        self.assertTrue(any("lead-owned brief" in e for e in verdict["errors"]), verdict)

    def test_the_preflight_never_runs_a_verifier_even_one_that_would_time_out(self):
        (self.project / "verdict").write_text("hang")
        self.init([self.verifier_task(timeout=0.5)])
        self.turn()
        self.verifier_receipt()
        started = time.monotonic()
        verdict = self.preflight()
        self.assertEqual(verdict["verdict"], OK, verdict)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(self.verifier_runs(), [], "the lead's check is the lead's; the preflight ran nothing")

    def test_preflight_ok_is_not_acceptance_a_failing_check_still_fails_at_the_lead(self):
        (self.project / "verdict").write_text("3")
        self.init([self.verifier_task()])
        self.turn()
        self.verifier_receipt()
        self.assertEqual(self.preflight()["verdict"], OK)
        self.assertEqual(self.lead_state()["tasks"]["7"]["status"], "sent", "the preflight accepted nothing")
        correction = self.turn()
        self.assertEqual((correction["action"], correction["next_attempt"]), ("correct", "7.2"), correction)
        self.assertIn("trusted verifier exited 3", correction["reason"])

    def test_the_preflight_writes_nothing(self):
        self.init()
        self.turn()
        for label, prepare in (("no receipt", lambda: None), ("missing", lambda: self.receipt(claim_status="untested")),
                               ("ok", lambda: self.receipt())):
            prepare()
            before = tree(self.root)
            verdict = self.preflight()
            self.assertEqual(tree(self.root), before, label)
            self.assertIn(verdict["verdict"], {OK, MISSING}, label)
        self.preflight(pane="scratch:p9")
        self.assertEqual(tree(self.root), before, "an unassigned pane writes nothing either")

    def test_a_worker_with_no_hook_is_still_gated_by_the_lead_alone(self):
        self.init()
        self.turn()
        self.receipt(content=b"wrong\n")
        self.ring("DONE 7 tasks/7.md")
        self.assertEqual(self.turn()["action"], "correct", "an unchecked claim does not pass without any hook")
        self.turn()
        self.receipt("7.2")
        self.ring("DONE 7.2 tasks/7.2.md")
        self.assertEqual(self.turn()["action"], "accept")
        self.assertFalse((self.root / "stop-hook.log").exists(), "no hook or preflight ran at any point")
        adapter = ADAPTER
        for name in ("lead.py", "resume.py"):
            self.assertNotIn("preflight", (adapter / name).read_text().lower(),
                             name + " must never read preflight or hook output")

    # ---- cannot-evaluate: a reason code, never a guess ----------------------------------------------

    def test_cannot_evaluate_names_its_reason(self):
        self.init()
        self.turn()
        self.assertEqual(self.preflight(pane="scratch:p9")["reason"], "unassigned_pane")
        self.receipt()
        self.ring("DONE 7 tasks/7.md")
        self.assertEqual(self.turn()["action"], "accept")
        done = self.preflight()
        self.assertEqual((done["verdict"], done["reason"]), (CANNOT, "nothing_in_flight"), done)
        (self.root / "lead-state.json").write_text("{not json")
        corrupt = self.preflight()
        self.assertEqual((corrupt["verdict"], corrupt["reason"]), (CANNOT, "record_corrupt"), corrupt)
        gone = run_preflight({"record_root": str(self.project / "no-such-record"), "pane_id": PANE})
        self.assertEqual((gone["verdict"], gone["reason"]), (CANNOT, "record_unavailable"), gone)

    def test_a_malformed_request_is_refused_before_anything_is_read(self):
        bad = [{"record_root": str(self.root)}, {"record_root": str(self.root), "pane_id": "../x"},
               {"record_root": str(self.root), "pane_id": "a/b"}, {"record_root": str(self.root), "pane_id": 7},
               {"pane_id": PANE}, {"record_root": str(self.root), "pane_id": PANE, "attempt": "3"},
               {"return": "relative.md", "attempt": "3", "matt": False},
               {"return": str(self.project / "a.md"), "attempt": "3.x", "matt": False},
               {"return": str(self.project / "a.md"), "attempt": "3", "matt": "yes"},
               {"return": str(self.project / "a.md"), "attempt": "3"},
               {"record_root": str(self.root), "pane_id": PANE, "extra": 1}]
        for params in bad:
            with self.subTest(params=params):
                response = run_preflight(params, expected=1)
                self.assertEqual(response["error"]["code"], "schema_invalid", response)

    # ---- the manual path: an assignment pin or an explicit {return, attempt, matt} triple -----------

    def manual_return(self, attempt="3", name="manual-3.md", closes=True, frontmatter=None, extra=""):
        path = self.project / name
        front = frontmatter if frontmatter is not None else (
            f"---\ntask: {attempt.split('.')[0]}\nattempt: {attempt}\nowner: kai\nlatitude: own\nkind: build\n"
            f"return: {path}\n---\n")
        text = front + "# Brief\n\n## Why\nA manual task.\n\n## Return\nWrite your return below this brief.\n"
        if closes:
            text += (f"\n## Return — attempt {attempt}\n\nCloses: {attempt}\n\n### Result\nDone.\n\n"
                     f"### Claims\n- tests: passed (ran the suite)\n\n### Evidence\nsuite output\n\n"
                     f"### Sidecars\n- none\n")
        path.write_text(text + extra)
        return path

    def pin(self, path, attempt="3", matt=False, pane=PANE):
        self.root.mkdir(exist_ok=True)
        (self.root / "assignments").mkdir(exist_ok=True)
        pin = {"return": str(path), "attempt": attempt, "matt": matt,
               "dispatched_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}
        (self.root / "assignments" / f"{pane}.json").write_text(json.dumps(pin))
        return pin

    def test_the_verdict_echoes_the_pins_dispatch_time_and_says_whether_the_return_closes_the_attempt(self):
        path = self.manual_return(attempt="9", name="manual-9.md", closes=False)
        pin = self.pin(path, attempt="9")
        open_verdict = run_preflight({"record_root": str(self.root), "pane_id": PANE})
        self.assertEqual((open_verdict["verdict"], open_verdict["dispatched_at"], open_verdict["closes"]),
                         (MISSING, pin["dispatched_at"], False), open_verdict)
        self.manual_return(attempt="9", name="manual-9.md")
        closed = run_preflight({"record_root": str(self.root), "pane_id": PANE})
        self.assertEqual((closed["verdict"], closed["dispatched_at"], closed["closes"]),
                         (OK, pin["dispatched_at"], True), closed)
        explicit = self.triple(path, "9")
        self.assertNotIn("dispatched_at", explicit, "only a pin carries a dispatch time")
        self.assertIs(explicit["closes"], True)

    def test_a_lead_record_verdict_says_whether_the_return_closes_the_attempt(self):
        self.init()
        self.turn()
        waiting = run_preflight({"record_root": str(self.root), "pane_id": PANE})
        self.assertEqual((waiting["verdict"], waiting["closes"]), (MISSING, False), waiting)
        self.receipt(claim_status="untested")
        bad = run_preflight({"record_root": str(self.root), "pane_id": PANE})
        self.assertEqual((bad["verdict"], bad["closes"]), (MISSING, True), "a return closes the attempt even when invalid")

    def test_the_explicit_triple_passes_a_valid_manual_return_and_reports_missing_ones(self):
        good = self.manual_return()
        verdict = self.triple(good, "3")
        self.assertEqual((verdict["verdict"], verdict["source"], verdict["attempt"]), (OK, "explicit", "3"), verdict)
        none_yet = self.manual_return(name="manual-4.md", attempt="4", closes=False)
        missing = self.triple(none_yet, "4")
        self.assertEqual(missing["verdict"], MISSING, missing)
        self.assertTrue(any("no Return section closes attempt 4" in e for e in missing["errors"]), missing)
        gone = self.triple(self.project / "never-written.md", "5")
        self.assertEqual((gone["verdict"], gone["errors"]), (MISSING, ["the assigned return file does not exist"]))

    def test_the_manual_path_writes_nothing_for_any_verdict(self):
        good = self.manual_return()
        none_yet = self.manual_return(name="manual-4.md", attempt="4", closes=False)
        self.pin(good)
        before = tree(self.project)
        for params in ({"return": str(good), "attempt": "3", "matt": False},
                       {"return": str(none_yet), "attempt": "4", "matt": False},
                       {"return": str(self.project / "never-written.md"), "attempt": "5", "matt": False},
                       {"record_root": str(self.root), "pane_id": PANE},
                       {"record_root": str(self.root), "pane_id": "scratch:p9"}):
            run_preflight(params)
            self.assertEqual(tree(self.project), before, params)

    def test_the_explicit_triple_is_validated_through_the_receipt_validator(self):
        incomplete = self.manual_return(name="manual-6.md", attempt="6", closes=False,
                                        extra="\n## Return — attempt 6\n\nCloses: 6\n\n### Result\nDone.\n")
        verdict = self.triple(incomplete, "6")
        self.assertEqual(verdict["verdict"], MISSING, verdict)
        self.assertTrue(any("Claims" in e or "Evidence" in e or "Sidecars" in e for e in verdict["errors"]), verdict)
        matt = self.triple(self.manual_return(), "3", matt=True)  # a Matt task needs the workflow record too
        self.assertEqual(matt["verdict"], MISSING, matt)
        self.assertTrue(matt["errors"], matt)

    def test_the_explicit_triple_rejects_a_brief_that_names_another_attempt_or_closes_it_twice(self):
        other = self.manual_return(attempt="3", name="other.md")
        wrong = self.triple(other, "3.2")
        self.assertEqual(wrong["verdict"], MISSING, wrong)
        self.assertTrue(any("frontmatter names attempt 3, not 3.2" in e for e in wrong["errors"]), wrong)
        nofront = self.manual_return(name="nofront.md", frontmatter="")
        self.assertIn("frontmatter names attempt none, not 3", self.triple(nofront, "3")["errors"])
        twice = self.manual_return(name="twice.md")
        with twice.open("a") as stream:
            stream.write("\n## Return — attempt 3\n\nCloses: 3\n\n### Result\nAgain.\n\n### Claims\n- tests: passed (x)\n"
                         "\n### Evidence\nx\n\n### Sidecars\n- none\n")
        self.assertTrue(any("2 Return sections close attempt 3" in e for e in self.triple(twice, "3")["errors"]))

    def test_a_fenced_example_in_a_manual_return_does_not_close_the_attempt(self):
        path = self.manual_return(name="fenced.md", closes=False,
                                  extra="\n## Example\n```markdown\n## Return — attempt 3\nCloses: 3\n```\n")
        verdict = self.triple(path, "3")
        self.assertEqual(verdict["verdict"], MISSING, verdict)
        self.assertTrue(any("no Return section closes attempt 3" in e for e in verdict["errors"]), verdict)

    def test_a_return_inside_an_html_comment_in_a_manual_return_does_not_close_the_attempt(self):
        path = self.manual_return(name="commented.md", closes=False,
                                  extra="\n<!--\n## Return — attempt 3\nCloses: 3\n-->\n")
        verdict = self.triple(path, "3")
        self.assertEqual((verdict["verdict"], verdict["closes"]), (MISSING, False), verdict)
        self.assertTrue(any("no Return section closes attempt 3" in e for e in verdict["errors"]), verdict)

    def test_the_triple_trusts_the_brief_it_is_given_so_it_is_feedback_only(self):
        # The "least sure of": a brief the lead did not write can be self-consistent. The triple path can only check
        # that file against itself, so a forged-but-valid return gets preflight-ok. That is acceptable only because
        # nothing accepts on it: lead.py and resume.py never read a preflight result (checked in the no-hook test).
        forged = self.manual_return(name="forged.md")
        self.assertEqual(self.triple(forged, "3")["verdict"], OK)
        self.assertEqual(self.triple(self.manual_return(attempt="9", name="elsewhere.md"), "3")["verdict"], MISSING,
                         "a brief written for another attempt is still caught")

    def test_an_assignment_pin_binds_a_pane_to_its_manual_task_when_there_is_no_lead_record(self):
        path = self.manual_return(closes=False)
        self.pin(path)
        self.assertFalse((self.root / "lead-state.json").exists())
        waiting = self.preflight()
        self.assertEqual((waiting["verdict"], waiting["source"]), (MISSING, "assignment-pin"), waiting)
        self.manual_return()
        self.pin(path)
        self.assertEqual(self.preflight()["verdict"], OK)
        self.assertEqual(self.preflight(pane="scratch:p9")["reason"], "unassigned_pane")

    def test_a_pin_that_is_malformed_or_unreadable_cannot_be_evaluated(self):
        self.root.mkdir()
        (self.root / "assignments").mkdir()
        for text in ("{not json", json.dumps({"return": "relative.md", "attempt": "3", "matt": False,
                                              "dispatched_at": "2026-10-16T16:00:00+00:00"}),
                     json.dumps({"return": str(self.project / "x.md"), "attempt": "3", "matt": False}),
                     json.dumps({"return": str(self.project / "x.md"), "attempt": "3", "matt": False,
                                 "dispatched_at": "yesterday"})):
            with self.subTest(pin=text[:40]):
                (self.root / "assignments" / f"{PANE}.json").write_text(text)
                verdict = self.preflight()
                self.assertEqual((verdict["verdict"], verdict["reason"]), (CANNOT, "pin_invalid"), verdict)

    def test_a_pane_that_is_a_record_member_uses_the_lead_record_before_any_pin(self):
        self.init()
        self.turn()
        self.receipt()
        self.pin(self.manual_return(closes=False))
        self.assertEqual(self.preflight()["source"], "lead-record")


if __name__ == "__main__":
    unittest.main()
