"""Resume through JSON commands, durable records and the disposable socket peer."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import unittest

import test_lead
import test_wake


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hashlib

import resume
from adapter import Refusal


class ResumeTest(unittest.TestCase):
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
    matt_workflow = test_lead.LeadTest.matt_workflow
    accepted_grilling = test_lead.LeadTest.accepted_grilling
    parent_record = test_lead.LeadTest.parent_record
    VERIFIER = test_lead.LeadTest.VERIFIER
    verifier_task = test_lead.LeadTest.verifier_task
    verifier_receipt = test_lead.LeadTest.verifier_receipt
    verifier_runs = test_lead.LeadTest.verifier_runs
    git = test_lead.LeadTest.git
    git_project = test_lead.LeadTest.git_project
    wake = test_wake.WakeTest.wake

    def resume(self, resume_id="return-1", expected=0, **params):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "resume.py"),
             "--socket", self.peer.path, "--state-dir", str(self.project / "adapter-state"),
             "--idle-seconds", "0.02", "--read-gap-seconds", "0.01"],
            input=json.dumps({"command": "resume", "params": {
                "record_root": str(self.root), "resume_id": resume_id, **params}}),
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        response = json.loads(result.stdout)
        return response.get("result", response)

    def refused_then_restored(self):
        """The lead refuses a receipt whose lead-owned brief prefix changed; the member restores it."""
        self.init()
        self.turn()
        path = self.receipt()
        good = path.read_text()
        path.write_text(good.replace("## Stop rule", "## Changed rule", 1))
        self.assertEqual(self.task_status(self.turn), "review-refused")
        return path, good

    def task_status(self, step=None):
        if step:
            step()
        return json.loads((self.root / "lead-state.json").read_text())["tasks"]["7"]["status"]

    def test_resume_never_accepts_a_review_refused_task(self):
        path, good = self.refused_then_restored()
        path.write_text(good)
        result = self.resume()
        row = result["plan"][0]
        self.assertNotEqual(row.get("trigger"), "accept", row)
        self.assertIn("review-refused", row["reason"])
        self.assertEqual(self.task_status(), "review-refused")
        self.assertNotEqual(result["handoff"], "lead")

    def test_resume_refuses_a_failed_mission_without_touching_it(self):
        path, good = self.refused_then_restored()
        self.assertEqual(self.turn()["action"], "mission-failed")
        path.write_text(good)
        before = (self.root / "lead-state.json").read_bytes()
        refused = self.resume(expected=1)
        self.assertEqual(refused["error"]["code"], "mission_failed", refused)
        self.assertEqual((self.root / "lead-state.json").read_bytes(), before)
        self.assertFalse((self.root / ".resume-latch").exists())

    def test_completed_unreported_is_checked_without_redispatch(self):
        self.init()
        self.turn()
        self.receipt()
        result = self.resume()
        self.assertEqual(result["plan"][0]["classification"], "completed-unreported")
        self.assertEqual(result["first_action"]["kind"], "accept")
        self.assertEqual(result["outcome"]["action"], "accept")
        self.assertEqual(len(self.sent_states), 1)
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["tasks"]["7"]["status"], "accepted")
        self.assertEqual(result["handoff"], "lead")
        again = self.resume()
        self.assertTrue(again["replayed"])
        self.assertEqual(result["first_action"], again["first_action"])
        self.assertEqual(len(self.sent_states), 1)

    def test_receipt_only_completion_with_an_unchanged_pane_reconciles_on_restart_without_redispatch(self):
        """A lost doorbell and no pane transition still wakes the lead, and restart accepts once."""
        self.init(wake={"mechanism": "wake.py in the lead pane", "deadline_seconds": 60})
        self.turn()
        pane = [(a["agent_status"], a["state_change_seq"]) for a in self.snapshot["agents"]]
        self.receipt()
        self.assertEqual([(a["agent_status"], a["state_change_seq"]) for a in self.snapshot["agents"]], pane)
        woke = self.wake(max_seconds=30)
        self.assertEqual((woke["reason"], woke["changes"]["panes"]), ("new_return", []))
        result = self.resume()
        self.assertEqual(result["plan"][0]["classification"], "completed-unreported")
        self.assertEqual(result["outcome"]["action"], "accept")
        self.assertEqual(len(self.sent_states), 1)
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["tasks"]["7"]["status"], "accepted")
        self.assertEqual(state["last_wake"]["reason"], "new_return")
        self.assertEqual(self.wake(max_seconds=1, slice_seconds=0.3)["reason"], "deadline")
        self.assertEqual(len(self.sent_states), 1)

    def test_trusted_verifier_runs_once_at_resume_acceptance_never_at_inspection(self):
        (self.project / "verdict").write_text("0")
        self.init([self.verifier_task()])
        self.turn()
        self.verifier_receipt()
        result = self.resume()
        self.assertEqual(result["plan"][0]["checks"][0]["verifier"], "deferred")
        self.assertEqual(result["outcome"]["action"], "accept", result)
        self.assertEqual(len(self.verifier_runs()), 1)
        proof = json.loads((self.root / result["outcome"]["evidence"]).read_text())
        self.assertEqual(proof["checks"][0]["exit"], 0)

    def test_hung_trusted_verifier_holds_resume_acceptance(self):
        (self.project / "verdict").write_text("hang")
        self.init([self.verifier_task(timeout=0.5)])
        self.turn()
        self.verifier_receipt()
        result = self.resume()
        self.assertEqual((result["outcome"]["action"], result["outcome"]["code"]),
                         ("hold", "verifier_unverified"), result)
        self.assertEqual(result["handoff"], "hold")
        self.assertNotEqual(self.state()["tasks"]["7"]["status"], "accepted")

    def test_verifier_exiting_at_its_timeout_is_unverified_not_an_error(self):
        # macOS refuses killpg on a group whose only member is the unreaped leader.
        original = resume.lead.os.killpg
        def exited_first(pgid, sig):
            os.kill(pgid, sig)  # the leader is gone but unreaped, as when it exits at the timeout
            raise PermissionError(1, "Operation not permitted")
        resume.lead.os.killpg = exited_first
        try:
            with self.assertRaises(Refusal) as raised:
                resume.lead.run_verifier({"check": ["/bin/sleep", "30"], "timeout_seconds": 0.05,
                                          "cwd": str(self.project)})
        finally:
            resume.lead.os.killpg = original
        self.assertEqual(raised.exception.code, "verifier_unverified")

    def test_resume_rows_carry_the_git_window_without_changing_classification(self):
        base = self.git_project()
        self.init()
        self.turn()
        (self.project / "work.txt").write_text("partial\n")
        self.git("add", "work.txt")
        self.git("commit", "-qm", "partial work")
        result = self.resume()
        row = result["plan"][0]
        self.assertEqual(row["classification"], "sent-unverified")
        self.assertEqual((row["git"]["base"], row["git"]["commits_ahead"]), (base, 1))
        self.assertNotIn("dirty", row["git"])
        self.assertEqual(len(self.sent_states), 1)

    def test_failing_git_at_resume_leaves_classification_unchanged(self):
        self.git_project()
        self.init()
        self.turn()
        fake = self.project / "fake-bin"
        fake.mkdir()
        (fake / "git").write_text("#!/bin/sh\necho fatal: broken >&2\nexit 128\n")
        (fake / "git").chmod(0o755)
        saved = os.environ["PATH"]
        os.environ["PATH"] = f"{fake}:{saved}"
        try:
            row = self.resume()["plan"][0]
        finally:
            os.environ["PATH"] = saved
        self.assertEqual((row["classification"], row["trigger"]), ("sent-unverified", "hold"))
        self.assertEqual(row["git"], "unavailable: fatal: broken")

    def test_slow_git_with_partial_stderr_is_unavailable_evidence_not_a_crash(self):
        fake = self.project / "fake-bin"
        fake.mkdir()
        (fake / "git").write_text("#!/bin/sh\necho warning: slow >&2\nsleep 5\n")
        (fake / "git").chmod(0o755)
        saved = resume.lead.GIT_TIMEOUT, os.environ["PATH"]
        resume.lead.GIT_TIMEOUT = 0.3
        os.environ["PATH"] = f"{fake}:{saved[1]}"
        try:
            head = resume.lead.git_head(str(self.project))
            window = resume.lead.git_window({"project_root": str(self.project)},
                                            {"active": "7", "git_base": {"7": "0" * 40}})
        finally:
            resume.lead.GIT_TIMEOUT, os.environ["PATH"] = saved
        self.assertTrue(head.startswith("unavailable"), head)
        self.assertTrue(window.startswith("unavailable"), window)
        timed_out = subprocess.TimeoutExpired(["git"], 0.3, stderr=b"warning: slow\n")
        self.assertEqual(resume.lead.git_unavailable(timed_out), "unavailable: warning: slow")

    def test_complete_matt_receipt_resumes_without_redispatch(self):
        workflow = self.matt_workflow()
        self.init([self.task(kind="research", workflow=workflow)])
        self.turn()
        path = self.receipt()
        with path.open("a") as stream:
            for value in workflow["skills"]:
                digest = hashlib.sha256(Path(value).read_bytes()).hexdigest()
                stream.write(f"Loaded: {value} | alpha: sha256:{digest} bytes:{len(Path(value).read_bytes())} fixture actual body read\n")
        result = self.resume()
        self.assertEqual(result["outcome"]["action"], "accept")
        self.assertEqual(result["handoff"], "lead")
        self.assertEqual(len(self.sent_states), 1)
        self.assertTrue(self.resume()["replayed"])
        self.assertEqual(len(self.sent_states), 1)

    def test_matt_resume_preserves_record_relative_procedure_paths(self):
        workflow = self.matt_workflow()
        procedure = self.project / "fixture-procedure.md"
        procedure.write_text("# Assigned procedure\nRead only the assigned greeting.\n")
        workflow["skills"].append("../../fixture-procedure.md")
        self.init([self.task(kind="research", workflow=workflow)])
        self.turn()
        path = self.receipt()
        with path.open("a") as stream:
            for value in workflow["skills"]:
                target = Path(value) if Path(value).is_absolute() else path.parent / value
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                stream.write(f"Loaded: {value} | alpha: sha256:{digest} fixture actual body read\n")
        result = self.resume()
        self.assertEqual(result["outcome"]["action"], "accept")
        self.assertEqual(len(self.sent_states), 1)

    def test_matt_accept_rechecks_growing_state_with_file_limits(self):
        workflow = self.matt_workflow()
        self.init([self.task(kind="research", workflow=workflow)])
        self.turn()
        path = self.receipt()
        with path.open("a") as stream:
            for value in workflow["skills"]:
                digest = hashlib.sha256(Path(value).read_bytes()).hexdigest()
                stream.write(f"Loaded: {value} | alpha: sha256:{digest} fixture actual body read\n")
        state, session = self.accept_session("growing-state")
        with Path(workflow["state"]).open("a") as stream:
            stream.write("x" * (resume.FILE_LIMIT + 1))
        with self.assertRaises(Refusal) as caught:
            resume.apply_first(self.root.resolve(), state, session, None, resume.Budget({}))
        self.assertEqual(caught.exception.code, "resume_budget")
        self.assertEqual(state["tasks"]["7"]["status"], "sent")
        self.assertFalse((self.root / "reviews/7.json").exists())

    def test_grilling_evidence_reread_obeys_existing_resume_file_limit(self):
        workflow = self.matt_workflow()
        evidence = self.accepted_grilling("accepted.md", "Inspect the task.", "Use the existing source.")
        workflow["grilling"] = "accepted: sha256:" + hashlib.sha256(evidence.read_bytes()).hexdigest() + " | " + str(evidence)
        self.init([self.task(kind="research", workflow=workflow)])
        self.turn()
        path = self.receipt()
        with path.open("a") as stream:
            for value in workflow["skills"]:
                digest = hashlib.sha256(Path(value).read_bytes()).hexdigest()
                stream.write(f"Loaded: {value} | alpha: sha256:{digest} fixture actual body read\n")
        state, session = self.accept_session("growing-grilling-evidence")
        evidence.write_text("x" * (resume.FILE_LIMIT + 1))
        with self.assertRaises(Refusal) as caught:
            resume.apply_first(self.root.resolve(), state, session, None, resume.Budget({}))
        self.assertEqual(caught.exception.code, "resume_budget")
        self.assertEqual(state["tasks"]["7"]["status"], "sent")
        self.assertFalse((self.root / "reviews/7.json").exists())

    def test_byte_count_receipt_cannot_bypass_the_resume_body_file_budget(self):
        workflow = self.matt_workflow()
        body = self.project / "large-procedure.md"
        body.write_text("Small assigned body.\n")
        workflow["skills"].append(str(body))
        self.init([self.task(kind="research", workflow=workflow)])
        self.turn()
        body.write_text("x" * (resume.FILE_LIMIT + 1))
        path = self.receipt()
        with path.open("a") as stream:
            for value in workflow["skills"]:
                data = Path(value).read_bytes()
                stream.write(f"Loaded: {value} | alpha: sha256:{hashlib.sha256(data).hexdigest()} bytes:{len(data)} fixture complete-buffer read\n")
        result = self.resume()
        self.assertEqual(result["handoff"], "hold")
        self.assertEqual(result["inspection_error"]["code"], "resume_budget")
        self.assertEqual(len(self.sent_states), 1)

    def test_matt_resume_contract_reads_obey_the_existing_file_budget(self):
        workflow = self.matt_workflow()
        self.init([self.task(kind="research", workflow=workflow)])
        self.turn()
        path = self.receipt()
        with path.open("a") as stream:
            for value in workflow["skills"]:
                digest = hashlib.sha256(Path(value).read_bytes()).hexdigest()
                stream.write(f"Loaded: {value} | alpha: sha256:{digest} fixture actual body read\n")
        with Path(workflow["state"]).open("a") as stream:
            stream.write("x" * (resume.FILE_LIMIT + 1))
        result = self.resume()
        self.assertEqual(result["handoff"], "hold")
        self.assertEqual(result["inspection_error"]["code"], "resume_budget")
        self.assertEqual(len(self.sent_states), 1)

    def state(self):
        return json.loads((self.root / "lead-state.json").read_text())

    def update_state(self, state):
        (self.root / "lead-state.json").write_text(json.dumps(state))

    def test_resume_does_not_dispatch_a_dependent_of_a_bounded_predecessor(self):
        self.add_member("beta", "scratch:p2")
        self.init([self.task("7"), self.task("8", owner="beta", after=["7"])])
        self.turn()
        self.receipt()
        self.assertEqual(self.turn()["action"], "accept")
        note = self.project / "bounded-scope.md"
        note.write_text("Task 7 accepted scope: hello only; the part task 8 needs is excluded.\n")
        self.command("record", {"record_root": str(self.root), "task": "7", "attempt": "7", "by": "lead",
                                "kind": "bounded", "identity": "c" * 64, "evidence": str(note)})
        sent = len(self.sent_states)
        result = self.resume()
        self.assertNotEqual(result["outcome"]["action"], "dispatch", result["outcome"])
        self.assertEqual(len(self.sent_states), sent, "the dependent of a bounded predecessor was not sent")

    def test_never_sent_dispatches_after_inspection_once(self):
        self.init()
        result = self.resume()
        self.assertEqual(result["plan"][0]["classification"], "never-sent")
        self.assertTrue(result["plan"][0]["pane_inspected"])
        self.assertEqual(result["outcome"]["action"], "dispatch")
        methods = [r["method"] for r in self.peer.requests]
        self.assertLess(methods.index("pane.read"), methods.index("pane.send_input"))
        self.assertIn("dispatching", self.sent_states[0])
        self.assertEqual(self.resume()["first_action"], result["first_action"])
        self.assertEqual(len(self.sent_states), 1)
        self.assertEqual(self.turn()["action"], "wait")

    def test_matt_dispatch_interrupted_after_delivery_resumes_with_identical_packet(self):
        workflow = self.matt_workflow()
        self.init([self.task(kind="research", workflow=workflow)])
        state = json.loads((self.root / "lead-state.json").read_text())
        rows, manifest = resume.lead.deliver(self.root.resolve(), state["tasks"]["7"], self.root.resolve() / "tasks/7.md")
        before = (self.root / manifest).read_bytes()
        result = self.resume()
        self.assertEqual(result["plan"][0]["classification"], "never-sent")
        self.assertEqual(result["outcome"]["action"], "dispatch")
        self.assertEqual(len(self.sent_states), 1)
        self.assertEqual((self.root / manifest).read_bytes(), before)
        brief = (self.root / "tasks/7.md").read_text()
        for row in rows:
            self.assertIn(f"{row['selected']} | sha256:{row['sha256']} bytes:{row['bytes']}", brief)

    def test_pane_reuse_is_refused_before_read_or_prompt(self):
        self.init()
        self.turn()
        state = self.state()
        state["tasks"]["7"]["status"] = "queued"  # stale team line, disk still pins old identity
        self.update_state(state)
        for item in (self.snapshot["panes"][0], self.snapshot["agents"][0]):
            item["terminal_id"] = "replacement-after-restart"
        before = len(self.peer.requests)
        result = self.resume()
        self.assertEqual(result["plan"][0]["code"], "identity_mismatch")
        self.assertEqual(result["plan"][0]["refused_actions"], ["prompt", "close"])
        self.assertEqual(result["handoff"], "hold")
        self.assertEqual([r["method"] for r in self.peer.requests[before:]], ["session.snapshot"])
        self.assertEqual(len(self.sent_states), 1)
        refused = self.command("lead", {"record_root": str(self.root)}, expected=1)
        self.assertEqual(refused["error"]["code"], "resume_required")

    def test_pane_replacement_between_inspection_and_guard_is_refused(self):
        self.init()
        reply = self.peer.reply

        def replace_after_read(request):
            response = reply(request)
            if request["method"] == "pane.read":
                for item in (self.snapshot["panes"][0], self.snapshot["agents"][0]):
                    item["terminal_id"] = "replacement-after-inspection"
            return response
        self.peer.reply = replace_after_read
        result = self.resume()
        self.assertEqual(result["outcome"]["action"], "refused")
        self.assertEqual(result["outcome"]["code"], "identity_mismatch")
        self.assertEqual(self.sent_states, [])

    def test_sent_prepared_refused_uncertain_are_never_retried(self):
        self.init()
        self.turn()
        record_path = next((self.project / "adapter-state/dispatches").glob("*/record.json"))
        record = json.loads(record_path.read_text())
        for status in ("sent", "prepared", "refused", "uncertain"):
            with self.subTest(status=status):
                record["status"] = status
                record_path.write_text(json.dumps(record))
                result = self.resume("return-" + status)
                self.assertEqual(result["plan"][0]["classification"], "sent-unverified")
                self.assertEqual(result["budget"]["used"]["pane_reads"], 1)
                self.assertEqual(result["handoff"], "hold")
                self.assertEqual(len(self.sent_states), 1)

    def test_task_line_without_dispatch_record_is_not_non_delivery(self):
        self.init()
        state = self.state()
        state["tasks"]["7"]["status"] = "dispatching"
        self.update_state(state)
        result = self.resume()
        self.assertEqual(result["handoff"], "hold")
        self.assertEqual(self.sent_states, [])

    def test_live_done_without_receipt_is_not_acceptance(self):
        self.init()
        self.ring("DONE 7 tasks/7.md")
        result = self.resume()
        self.assertEqual(result["plan"][0]["classification"], "completed-unreported")
        self.assertEqual(result["outcome"]["action"], "hold")
        self.assertEqual(self.sent_states, [])

    def test_late_done_cannot_close_current_attempt(self):
        self.init()
        self.turn()
        self.receipt(content=b"wrong\n")
        self.turn()
        self.ring("DONE 7 tasks/7.md")
        result = self.resume()
        self.assertEqual(result["plan"][0]["attempt"], "7.2")
        self.assertEqual(result["outcome"]["action"], "hold")
        self.assertNotEqual(self.state()["tasks"]["7"]["status"], "accepted")
        self.assertEqual(len(self.sent_states), 1)

    def test_accepted_record_is_rechecked_not_blindly_trusted(self):
        self.init()
        self.turn()
        self.receipt()
        self.turn()
        result = self.resume()
        self.assertEqual(result["plan"][0]["classification"], "completed-and-reported")
        self.assertEqual(result["handoff"], "lead")
        (self.root / "tasks/7/result.txt").write_text("changed\n")
        self.assertEqual(self.resume("changed")["handoff"], "hold")

    def test_budget_stops_without_census_or_dispatch(self):
        self.add_member("beta", "scratch:p2")
        self.init([self.task(), self.task("8", "beta")])
        result = self.resume(max_pane_reads=1)
        self.assertEqual(result["budget"]["used"]["pane_reads"], 1)
        self.assertEqual(result["uninspected_tasks"], 1)
        self.assertEqual(result["inspection_error"]["code"], "resume_budget")
        self.assertEqual(result["outcome"]["action"], "hold")
        self.assertEqual(self.sent_states, [])

    def test_task_budget_leaves_remaining_tasks_uninspected(self):
        self.init([self.task(), self.task("8")])
        result = self.resume(max_tasks=1)
        self.assertEqual(result["uninspected_tasks"], 1)
        self.assertEqual(result["budget"]["used"]["tasks"], 1)
        self.assertEqual(result["handoff"], "hold")

    def test_disk_read_cap_fails_closed(self):
        self.init()
        result = self.resume(max_disk_reads=2)
        self.assertEqual(result["inspection_error"]["code"], "resume_budget")
        self.assertEqual(result["budget"]["used"]["disk_reads"], 2)
        self.assertEqual(self.sent_states, [])

    def test_missing_reserved_record_is_not_never_sent(self):
        self.init()
        state = self.state()
        (self.project / "adapter-state/dispatches" / (state["namespace"] + "-7")).mkdir(parents=True)
        result = self.resume()
        self.assertEqual(result["plan"][0]["code"], "dispatch_incomplete")
        self.assertEqual(self.sent_states, [])

    def test_interrupted_first_dispatch_never_replays(self):
        self.init()
        result = self.resume()
        path = self.root / "resumes/return-1.json"
        journal = json.loads(path.read_text())
        journal["status"] = "started"  # crash after send, before final resume write
        path.write_text(json.dumps(journal))
        recovered = self.resume()
        self.assertEqual(recovered["first_action"], result["first_action"])
        self.assertEqual(recovered["outcome"]["action"], "hold")
        self.assertEqual(len(self.sent_states), 1)
        self.receipt()
        reconciled = self.resume("new-evidence")
        self.assertEqual(reconciled["outcome"]["action"], "accept")
        self.assertEqual(len(self.sent_states), 1)

    def test_fifo_evidence_is_refused_without_waiting(self):
        self.init()
        path = self.root / "tasks/7.md"
        path.parent.mkdir()
        os.mkfifo(path)
        started = time.monotonic()
        result = self.resume()
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(result["inspection_error"]["code"], "resume_budget")
        self.assertEqual(self.sent_states, [])

    def test_compliance_still_gates_resume_dispatch(self):
        self.init([self.task(planned_commands=["git push origin main --force"])])
        result = self.resume()
        self.assertEqual(result["outcome"]["action"], "compliance-refused")
        self.assertEqual(self.sent_states, [])

    def test_identity_sequence_regression_refuses(self):
        self.init()
        self.snapshot["agents"][0]["state_change_seq"] = 10
        self.turn()
        self.snapshot["agents"][0]["state_change_seq"] = 1
        result = self.resume()
        self.assertEqual(result["plan"][0]["code"], "identity_mismatch")
        self.assertEqual(len(self.sent_states), 1)

    def test_deadline_stops_a_stalled_snapshot(self):
        # Two bounded timers race here by design: the SIGALRM reconciliation
        # budget and the request's own deadline are both deadline_seconds, so
        # timer slack decides which refusal lands first. Either one stops the
        # stall inside the bound; the inspection must never outlive either.
        self.init()

        def stall(request):
            time.sleep(0.4)
            return None
        self.peer.reply = stall
        result = self.resume(deadline_seconds=0.05)
        # CLI startup and post-inspection durable writes are outside this budget;
        # measure the inspection itself. The public helper still caps the command.
        self.assertLess(result["budget"]["elapsed_seconds"], 0.35)
        self.assertIn(result["inspection_error"]["code"],
                      {"resume_budget", "transport_error"})
        self.assertEqual(result["handoff"], "hold")
        self.assertEqual(self.sent_states, [])

    def test_draft_guard_is_not_replaced_by_resume_inspection(self):
        self.init()
        self.screens["scratch:p1"] = "[INPUT]\nhuman draft\n[/INPUT]\n"
        result = self.resume()
        self.assertEqual(result["outcome"]["action"], "refused")
        self.assertIn("draft", result["outcome"]["reason"])
        self.assertEqual(self.sent_states, [])

    def test_old_resume_id_cannot_release_new_hold(self):
        self.init()
        self.resume()
        self.resume("new-hold")
        replay = self.resume()
        self.assertEqual(replay["handoff"], "hold")
        self.assertEqual(self.state()["resume_gate"]["id"], "new-hold")
        self.assertEqual(len(self.sent_states), 1)

    def test_corrupt_guard_record_is_a_durable_hold(self):
        self.init()
        self.turn()
        path = next((self.project / "adapter-state/dispatches").glob("*/record.json"))
        record = json.loads(path.read_text())
        record["guard"] = []
        path.write_text(json.dumps(record))
        result = self.resume()
        self.assertEqual(result["plan"][0]["code"], "dispatch_incomplete")
        self.assertEqual(result["handoff"], "hold")
        self.assertEqual(len(self.sent_states), 1)

    def test_first_action_is_journaled_before_member_input(self):
        self.init()
        journals = []
        reply = self.peer.reply

        def capture(request):
            if request["method"] == "pane.send_input":
                journals.append(json.loads((self.root / "resumes/return-1.json").read_text()))
            return reply(request)
        self.peer.reply = capture
        result = self.resume()
        self.assertEqual(len(journals), 1)
        self.assertEqual(journals[0]["status"], "started")
        self.assertEqual(journals[0]["first_action"], result["first_action"])
        self.assertEqual(journals[0]["first_action"]["kind"], "dispatch")

    def test_total_byte_cap_holds_before_large_return(self):
        self.init()
        path = self.root / "tasks/7.md"
        path.parent.mkdir()
        path.write_text("x" * 20000)
        result = self.resume(max_bytes=10000)
        self.assertEqual(result["inspection_error"]["code"], "resume_budget")
        self.assertLessEqual(result["budget"]["used"]["bytes"], 10000)
        self.assertEqual(self.sent_states, [])

    def test_symlink_receipt_escape_is_not_read(self):
        self.init()
        path = self.root / "tasks/7.md"
        path.parent.mkdir()
        private = self.project / "outside.txt"
        private.write_text("private fixture data")
        path.symlink_to(private)
        result = self.resume()
        self.assertEqual(result["plan"][0]["code"], "path_outside_record")
        self.assertEqual(result["handoff"], "hold")
        self.assertEqual(self.sent_states, [])

    def test_close_command_has_no_control_surface(self):
        self.init()
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "resume.py"),
             "--socket", self.peer.path],
            input=json.dumps({"command": "close", "params": {"pane_id": "scratch:p1"}}),
            text=True, capture_output=True, timeout=5,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "unknown_command")
        self.assertEqual(self.peer.requests, [])

    def test_late_receipt_does_not_override_explicit_stop(self):
        self.init()
        self.turn()
        state = self.state()
        state["tasks"]["7"]["status"] = "stopped"
        self.update_state(state)
        self.receipt()
        result = self.resume()
        self.assertEqual(result["outcome"]["action"], "hold")
        self.assertEqual(self.state()["tasks"]["7"]["status"], "stopped")

    def test_done_memory_survives_new_resume_id_and_cleared_viewport(self):
        self.init()
        self.ring("DONE 7 tasks/7.md")
        self.assertEqual(self.resume()["handoff"], "hold")
        self.screens["scratch:p1"] = "[INPUT]\n\n[/INPUT]\n"
        resumed = self.resume("after-viewport-clear")
        self.assertEqual(resumed["handoff"], "hold")
        self.assertEqual(self.sent_states, [])
        self.assertNotEqual(resumed["plan"][0]["classification"], "never-sent")

    def test_pending_done_prevents_dispatch_without_visible_ring(self):
        self.init()
        state = self.state()
        state["pending"].append({
            "type": "DONE", "task": "7", "attempt": None, "artifact": "tasks/7.md",
            "member": "alpha", "line": "DONE 7 tasks/7.md", "source": "pane",
        })
        self.update_state(state)
        self.assertEqual(self.resume()["handoff"], "hold")
        self.assertEqual(self.sent_states, [])

    def assert_latched(self):
        before = len(self.peer.requests)
        refused = self.command("lead", {"record_root": str(self.root)}, expected=1)
        self.assertEqual(refused["error"]["code"], "resume_required")
        self.assertEqual(len(self.peer.requests), before, "latched lead must not use a socket")

    def test_index_budget_failure_latches_before_inspection(self):
        self.init()
        self.assertEqual(self.resume(max_bytes=1, expected=1)["error"]["code"], "resume_budget")
        self.assert_latched()
        self.assertEqual(self.sent_states, [])
        self.assertEqual(self.resume("fresh-inspection")["handoff"], "lead")
        self.assertEqual(self.turn()["action"], "wait")

    def test_journal_budget_failure_latches_before_inspection(self):
        self.init()
        self.assertEqual(self.resume(max_disk_reads=1, expected=1)["error"]["code"], "resume_budget")
        self.assert_latched()
        self.assertEqual(self.sent_states, [])

    def test_corrupt_journal_cannot_leave_old_ready_gate_open(self):
        self.init()
        state = self.state()
        state["resume_gate"] = {"id": "old", "status": "ready"}
        self.update_state(state)
        (self.root / "resumes").mkdir()
        (self.root / "resumes/return-1.json").write_text("{")
        self.resume(expected=1)
        self.assert_latched()
        self.assertEqual(self.sent_states, [])

    def test_restoring_corrupt_index_does_not_clear_latch(self):
        self.init()
        original = self.state()
        (self.root / "lead-state.json").write_text("{")
        self.resume(expected=1)
        self.update_state(original)
        self.assert_latched()
        self.assertEqual(self.sent_states, [])

    def held_task(self):
        self.init()
        self.turn()
        self.ring("HELD 7 clarify original scope")
        self.assertEqual(self.turn()["action"], "escalate")
        self.assertEqual(self.resume()["handoff"], "hold")

    def test_human_answer_is_processed_file_only_under_resume_hold(self):
        self.held_task()
        self.command("answer", {
            "record_root": str(self.root), "escalation": "1", "by": "fixture-human",
            "decision": "continue", "answer": "Continue within the original brief.",
        })
        before = len(self.peer.requests)
        result = self.resume("human-decision")
        self.assertEqual(result["outcome"]["action"], "human-answer")
        self.assertEqual(len(self.peer.requests), before, "human answer path is file-only")
        self.assertEqual(result["handoff"], "hold", "an answer does not reconcile delivery")
        self.assert_latched()
        self.assertEqual(self.state()["escalations"][0]["status"], "answered")
        self.assertIn("fixture-human", (self.root / "answers/7-human.md").read_text())
        self.assertEqual(self.resume("human-decision")["outcome"], result["outcome"])
        self.receipt()
        self.assertEqual(self.resume("checked-return")["outcome"]["action"], "accept")
        self.assertEqual(len(self.sent_states), 1)

    def test_invalid_human_answer_is_refused_under_resume_hold(self):
        self.held_task()
        (self.root / "human-answers").mkdir()
        (self.root / "human-answers/1.json").write_text(json.dumps({
            "escalation": "2", "by": "fixture-human", "decision": "continue", "answer": "yes",
        }))
        before = len(self.peer.requests)
        result = self.resume("misfiled-answer")
        self.assertEqual(result["outcome"]["code"], "invalid_answer")
        self.assertEqual(len(self.peer.requests), before)
        self.assertEqual(self.state()["escalations"][0]["status"], "waiting")
        self.assertFalse((self.root / "answers/7-human.md").exists())
        self.assert_latched()

    def test_pane_response_cap_stops_before_waiting_for_full_frame(self):
        self.init()
        # Send enough bytes to exceed max_bytes, then keep the NDJSON frame open.
        self.peer.close()
        Path(self.peer.path).unlink()
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(self.peer.path)
        listener.listen()
        listener.settimeout(2)
        closed = threading.Event()
        release = threading.Event()
        errors = []

        def serve():
            try:
                with listener:
                    for _ in range(2):
                        conn, _ = listener.accept()
                        with conn, conn.makefile("rb") as stream:
                            request = json.loads(stream.readline())
                            if request["method"] == "session.snapshot":
                                conn.sendall((json.dumps({
                                    "id": request["id"], "result": {"snapshot": self.snapshot},
                                }) + "\n").encode())
                            else:
                                conn.sendall(b"x" * 10001)  # No newline: do not wait for the remainder.
                                conn.settimeout(0.5)
                                if conn.recv(1) == b"":
                                    closed.set()
                                release.wait(2)
            except Exception as error:
                errors.append(error)

        server = threading.Thread(target=serve, daemon=True)
        server.start()
        try:
            result = self.resume(max_bytes=10000, deadline_seconds=2)
            self.assertTrue(closed.wait(0.1), errors)
            self.assertEqual(result["inspection_error"]["code"], "resume_budget")
            self.assertLessEqual(result["budget"]["used"]["bytes"], 10000)
            self.assertEqual(self.sent_states, [])
            self.assert_latched()
        finally:
            release.set()
            server.join(3)

    def test_resume_uses_lead_final_identity_check_after_guard(self):
        self.init()
        reply = self.peer.reply

        def replace_after_guard(request):
            if request["method"] == "session.snapshot":
                if list((self.project / "adapter-state/dispatches").glob("*/record.json")):
                    for row in self.snapshot["agents"] + self.snapshot["panes"]:
                        row["terminal_id"] = "replacement-after-guard"
            return reply(request)

        self.peer.reply = replace_after_guard
        result = self.resume()
        self.assertEqual(result["outcome"]["action"], "uncertain")
        self.assertEqual(self.sent_states, [])
        self.assert_latched()
        record = next((self.project / "adapter-state/dispatches").glob("*/record.json"))
        self.assertIn("identity", json.loads(record.read_text())["error"])

    def test_help_memory_is_attempt_scoped_and_survives_viewport_clear(self):
        self.init()
        self.ring("HELP 7 which greeting")
        self.assertEqual(self.resume()["handoff"], "hold")
        self.screens["scratch:p1"] = "[INPUT]\n\n[/INPUT]\n"
        self.assertEqual(self.resume("cleared-help")["handoff"], "hold")
        state = self.state()
        self.assertIn("7", state["tasks"]["7"]["delivery_observed"])
        self.assertEqual(self.sent_states, [])
        state["tasks"]["7"].update({"active": "7.2", "status": "queued", "return": "tasks/7.2.md"})
        self.update_state(state)
        result = self.resume("explicit-correction-attempt")
        self.assertEqual(result["outcome"]["action"], "dispatch")
        self.assertEqual(result["plan"][0]["attempt"], "7.2")
        self.assertEqual(len(self.sent_states), 1)

    def test_old_finished_journal_cannot_clear_early_failure_latch(self):
        self.init()
        self.assertEqual(self.resume()["handoff"], "lead")
        self.resume("early-failure", max_bytes=1, expected=1)
        self.assertEqual(self.resume()["handoff"], "hold")
        self.assert_latched()
        self.assertEqual(len(self.sent_states), 1)

    def test_human_answer_budget_fails_before_mutation(self):
        self.held_task()
        self.command("answer", {
            "record_root": str(self.root), "escalation": "1", "by": "fixture-human",
            "decision": "continue", "answer": "Keep the original scope.",
        })
        before = len(self.peer.requests)
        result = self.resume("bounded-answer", max_disk_reads=3)
        self.assertEqual(result["outcome"]["code"], "resume_budget")
        self.assertEqual(result["budget"]["used"]["disk_reads"], 3)
        self.assertEqual(len(self.peer.requests), before)
        self.assertEqual(self.state()["escalations"][0]["status"], "waiting")
        self.assertFalse((self.root / "answers/7-human.md").exists())
        self.assert_latched()

    def test_bounded_pane_reader_preserves_response_id_validation(self):
        self.init()
        reply = self.peer.reply

        def wrong_id(request):
            if request["method"] == "pane.read":
                return (json.dumps({"id": "wrong", "result": reply(request)}) + "\n").encode()
            return reply(request)

        self.peer.reply = wrong_id
        result = self.resume()
        self.assertEqual(result["plan"][0]["code"], "transport_error")
        self.assertEqual(result["handoff"], "hold")
        self.assertEqual(self.sent_states, [])

    def test_corrupt_delivery_marker_is_not_absence_of_delivery(self):
        self.init()
        state = self.state()
        state["tasks"]["7"]["delivery_observed"] = {"7": {}}
        self.update_state(state)
        result = self.resume()
        self.assertEqual(result["handoff"], "hold")
        self.assertEqual(self.sent_states, [])

    def accept_session(self, session_id):
        state = json.loads((self.root / "lead-state.json").read_text())
        row = {"task": "7", "attempt": "7", "trigger": "accept",
               "receipt_sha256": hashlib.sha256(
                   (self.root / "tasks/7.md").read_bytes()).hexdigest()}
        return (state, {"id": session_id, "plan": [row],
                        "first_action": {"kind": "accept", "task": "7"}})

    def test_accept_holds_when_artifact_changed_after_inspection(self):
        # Ticket 10: acceptance anchors to the artifact as it exists at accept time.
        # A return that changed after inspection holds; it is never accepted on
        # stale evidence.
        self.init()
        self.turn()
        self.receipt()
        state, session = self.accept_session("changed-1")
        with (self.root / "tasks/7.md").open("a") as stream:
            stream.write("late member write\n")
        with self.assertRaises(Refusal) as caught:
            resume.apply_first(self.root.resolve(), state, session, None, resume.Budget({}))
        self.assertEqual(caught.exception.code, "artifact_changed")
        self.assertEqual(state["tasks"]["7"]["status"], "sent")
        self.assertFalse((self.root / "reviews/7.json").exists())

    def test_accept_refuses_a_return_swapped_for_a_fifo_without_waiting(self):
        self.init()
        self.turn()
        self.receipt()
        state, session = self.accept_session("fifo-1")
        path = self.root / "tasks/7.md"
        path.unlink()
        os.mkfifo(path)
        outcome = []

        def accept():
            try:
                resume.apply_first(self.root.resolve(), state, session, None, resume.Budget({}))
                outcome.append("accepted")
            except Refusal as error:
                outcome.append(error.code)

        thread = threading.Thread(target=accept, daemon=True)
        thread.start()
        thread.join(5)
        if thread.is_alive():
            os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))  # release the blocked reader
            thread.join(5)
            self.fail("acceptance blocked on a FIFO return")
        self.assertEqual(outcome, ["resume_budget"])
        self.assertFalse((self.root / "reviews/7.json").exists())

    def test_resume_deadline_during_dispatch_leaves_the_task_uncertain(self):
        self.init()
        state = json.loads((self.root / "lead-state.json").read_text())
        state["members"]["alpha"]["identity"] = {}

        def deadline_mid_send(*args):
            raise Refusal("resume_budget", "reconciliation deadline reached")
        dispatch = resume.lead.dispatch
        self.addCleanup(setattr, resume.lead, "dispatch", dispatch)
        resume.lead.dispatch = deadline_mid_send
        entry = resume.lead.send_task(None, self.root.resolve(), state, state["tasks"]["7"], None)
        self.assertEqual((entry["action"], state["tasks"]["7"]["status"]), ("uncertain", "uncertain"))

    def test_accept_holds_when_claims_fail_the_live_recheck(self):
        # Ticket 10: the artifact digest may match, but the claim checks are re-run
        # against the sidecar as it exists now, not as inspection remembered it.
        self.init()
        self.turn()
        self.receipt()
        state, session = self.accept_session("claims-1")
        (self.root / "tasks/7/result.txt").write_bytes(b"goodbye\n")
        with self.assertRaises(Refusal) as caught:
            resume.apply_first(self.root.resolve(), state, session, None, resume.Budget({}))
        self.assertEqual(caught.exception.code, "claims_failed_recheck")
        self.assertEqual(state["tasks"]["7"]["status"], "sent")
        self.assertFalse((self.root / "reviews/7.json").exists())

    def test_accept_on_unchanged_artifact_passes_the_live_recheck(self):
        # Control: nothing changed between inspection and acceptance.
        self.init()
        self.turn()
        self.receipt()
        state, session = self.accept_session("clean-1")
        entry = resume.apply_first(self.root.resolve(), state, session, None, resume.Budget({}))
        self.assertEqual(entry["action"], "accept")
        self.assertEqual(state["tasks"]["7"]["status"], "accepted")
        proof = json.loads((self.root / "reviews/7.json").read_text())
        self.assertEqual(proof["receipt_sha256"],
                        session["plan"][0]["receipt_sha256"])
        self.assertEqual(proof["errors"], [])

    def test_accept_proof_digest_describes_the_reviewed_receipt_bytes(self):
        # Round 3 (S-3): a member write between the digest and a rereading review
        # could make the proof digest describe bytes the review never saw. The
        # hash and the review now share one read of the receipt.
        import lead

        self.init()
        self.turn()
        self.receipt()
        state, session = self.accept_session("identity-1")
        path = self.root / "tasks/7.md"
        before = path.read_bytes()
        seen = {}
        original = lead.review_receipt

        def appending_review(root, task, ring, text=None):
            seen["text"] = text
            with path.open("a") as stream:  # deterministic mid-accept member write
                stream.write("\n")
            return original(root, task, ring, text=text)

        lead.review_receipt = appending_review
        try:
            entry = resume.apply_first(self.root.resolve(), state, session, None, resume.Budget({}))
        finally:
            lead.review_receipt = original
        self.assertEqual(entry["action"], "accept")
        self.assertNotEqual(path.read_bytes(), before, "the member write did land")
        proof = json.loads((self.root / "reviews/7.json").read_text())
        # The proof digest is the digest of exactly the bytes the review consumed.
        self.assertEqual(proof["receipt_sha256"],
                         hashlib.sha256(seen["text"].encode()).hexdigest())
        self.assertEqual(proof["receipt_sha256"], session["plan"][0]["receipt_sha256"])


    def test_prose_mentioning_the_frame_token_does_not_hide_a_visible_done(self):
        # External review A1: resume cut the screen at the first substring match of the frame token.
        self.init()
        self.screens["scratch:p1"] = ("Renderer uses [INPUT] as its frame token.\nDONE 7 tasks/7.md\n"
                                      "[INPUT]\n\n[/INPUT]\n")
        result = self.resume()
        self.assertEqual(result["plan"][0]["classification"], "completed-unreported")
        self.assertEqual(result["handoff"], "hold")
        self.assertEqual(self.sent_states, [])

    def assert_corrupt_index_refused_and_latched(self, corrupt):
        # External review A4: valid JSON with the wrong shape must refuse structurally, never dispatch.
        self.init()
        (self.root / "lead-state.json").write_text(corrupt)
        before = len(self.peer.requests)
        refused = self.resume(expected=1)
        self.assertEqual(refused["error"]["code"], "record_corrupt")
        self.assertIn("restore", refused["error"]["message"])
        self.assertEqual(len(self.peer.requests), before, "corrupt state must not use the socket")
        self.assertTrue((self.root / ".resume-latch").exists())
        self.assert_latched()
        self.assertEqual(self.sent_states, [])

    def test_an_array_lead_state_is_refused_and_keeps_the_fresh_latch(self):
        self.assert_corrupt_index_refused_and_latched("[]")

    def test_a_null_lead_state_is_refused_and_keeps_the_fresh_latch(self):
        self.assert_corrupt_index_refused_and_latched("null")

    def test_an_empty_object_lead_state_is_refused_and_keeps_the_fresh_latch(self):
        self.assert_corrupt_index_refused_and_latched("{}")


if __name__ == "__main__":
    unittest.main()
