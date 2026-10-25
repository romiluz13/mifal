"""Lead behavior at the JSON command + durable record + socket seam."""

import contextlib
import glob
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

from test_cli import Peer, PANE, AGENT, SNAPSHOT


CLI = Path(__file__).resolve().parents[1] / "lead.py"


class LeadTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lead-test-", dir="/tmp")
        self.project = Path(self.temp.name)
        self.root = self.project / ".team"
        self.peer = Peer(self.project)
        self.snapshot = json.loads(json.dumps(SNAPSHOT))
        self.screens = {"scratch:p1": "[INPUT]\n\n[/INPUT]\n"}
        self.sent_states = []
        (self.project / "AGENTS.md").write_text("- Never run `git push --force`.\n")
        self.session_log = self.project / "fixture-session.log"
        self.session_log.write_text("\n".join([
            '"skip the retrospective for this fixture"', '"ship it"', '"skip the source plan, I have the sources"']) + "\n")

        def reply(request):
            if request["method"] == "session.snapshot":
                return {"snapshot": self.snapshot}
            if request["method"] == "pane.read":
                pane = request["params"]["pane_id"]
                return {"read": {"pane_id": pane, "truncated": False, "text": self.screens[pane]}}
            if request["method"] == "pane.send_input":
                self.sent_states.append((self.root / "state.md").read_text())
            return {"type": "input_sent"}
        self.peer.reply = reply

    def tearDown(self):
        self.peer.close()
        self.temp.cleanup()

    def command(self, command, params, expected=0):
        result = subprocess.run(
            [sys.executable, str(CLI), "--socket", self.peer.path,
             "--state-dir", str(self.project / "adapter-state"),
             "--idle-seconds", "0.02", "--read-gap-seconds", "0.01"],
            input=json.dumps({"command": command, "params": params}),
            text=True, capture_output=True, timeout=10,
            env={**os.environ, "HERDR_PANE_ID": "human:p1"},
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def task(self, task_id="7", owner="alpha", **changes):
        return {
            "id": task_id, "owner": owner, "why": "Produce a checked micro-mission artifact.",
            "outcome": "Write hello with a newline.", "value": 10,
            "claims": {"greeting": {"path": f"tasks/{task_id}/result.txt",
                                  "sha256": hashlib.sha256(b"hello\n").hexdigest()}},
            "stop_rule": "Stop after two attempts; report what failed.",
            "planned_commands": [], "files_changed": [f"tasks/{task_id}/result.txt"],
            "help_answers": {"which greeting": "Use hello, followed by a newline."},
            **changes,
        }

    def init_params(self, tasks=None, **extra):
        return {
            "record_root": str(self.root), "project_root": str(self.project),
            "workspace_id": "scratch", "lead_pane_id": "scratch:lead",
            "mission": "All required greetings independently checked.",
            "members": [{"name": a["name"], "pane_id": a["pane_id"],
                         "input_box": {"agent": "fake", "start": "[INPUT]", "end": "[/INPUT]"}}
                        for a in self.snapshot["agents"]],
            "tasks": tasks or [self.task()],
            **extra,
        }

    def init(self, tasks=None, **extra):
        return self.command("init", self.init_params(tasks, **extra))

    def turn(self):
        return self.command("lead", {"record_root": str(self.root), "wait_seconds": 0.03})["result"]

    def add_member(self, name, pane):
        self.snapshot["panes"].append({**PANE, "pane_id": pane, "terminal_id": name})
        self.snapshot["agents"].append({**AGENT, "pane_id": pane, "terminal_id": name, "name": name})
        self.screens[pane] = "[INPUT]\n\n[/INPUT]\n"

    def ring(self, line, pane="scratch:p1"):
        self.screens[pane] = line + "\n[INPUT]\n\n[/INPUT]\n"
        next(a for a in self.snapshot["agents"] if a["pane_id"] == pane)["state_change_seq"] += 1

    def receipt(self, active="7", content=b"hello\n", claim_status="passed"):
        base = active.split(".")[0]
        path = self.root / f"tasks/{active}.md"
        sidecar = self.root / f"tasks/{base}/result.txt"
        sidecar.parent.mkdir(exist_ok=True, parents=True)
        sidecar.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        with path.open("a") as stream:
            stream.write(f"\n## Return — attempt {active}\n\nCloses: {active}\n\n"
                         f"### Result\n{sidecar}\n\n### Claims\n"
                         f"- greeting: {claim_status} (sha256 {digest})\n\n"
                         f"### Evidence\n{sidecar}\n\n### Sidecars\n- tasks/{base}/result.txt\n")
        return path

    def test_dispatch_records_task_before_guarded_send(self):
        self.init()
        result = self.turn()
        self.assertEqual((result["moment"], result["action"]), ("M2", "dispatch"))
        self.assertEqual(result["task"], "7")
        self.assertIn("7 | alpha | 7 | dispatching", self.sent_states[0])
        brief = (self.root / "tasks/7.md").read_text()
        self.assertIn("## Done means", brief)
        self.assertIn("## Stop rule", brief)
        self.assertEqual(len(self.sent_states), 1)
        self.assertTrue((self.root / "compliance-log.jsonl").exists())
        self.assertEqual(self.turn()["action"], "wait")
        self.assertEqual(len(self.sent_states), 1, "never re-dispatch on idle or restart")

    def test_blocked_then_report_then_idle_by_leverage(self):
        self.add_member("beta", "scratch:p2")
        self.add_member("gamma", "scratch:p3")
        self.init([self.task(value=30), self.task("8", "beta", value=20),
                   self.task("9", "gamma", value=10)])
        self.assertEqual(self.turn()["task"], "7")
        self.assertEqual(self.turn()["task"], "8")
        self.receipt("8")
        self.ring("DONE 8 tasks/8.md", "scratch:p2")
        self.ring("HELP 7 which greeting")
        answer = self.turn()
        self.assertEqual(answer["action"], "answer-help")
        self.assertEqual([c["priority"] for c in answer["candidates"]], [300, 200, 100])
        self.assertIn("Use hello", (self.root / answer["evidence"]).read_text())
        self.assertEqual(self.turn()["action"], "accept")
        self.assertEqual(self.turn()["task"], "9")

    def test_correction_rejects_late_done_and_checks_actual_artifact(self):
        self.init()
        self.turn()
        self.receipt(content=b"wrong\n")
        self.ring("DONE 7 tasks/7.md")
        correction = self.turn()
        self.assertEqual(correction["action"], "correct")
        self.assertEqual(correction["next_attempt"], "7.2")
        self.assertEqual(self.turn()["task"], "7.2")
        self.ring("DONE 7 tasks/7.md")
        late = self.turn()
        self.assertEqual(late["action"], "reject-doorbell")
        self.assertIn("7.2", late["reason"])
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["tasks"]["7"]["status"], "sent")
        self.receipt("7.2")
        self.ring("DONE 7.2 tasks/7.2.md")
        self.assertEqual(self.turn()["action"], "accept")
        self.assertEqual(self.turn()["action"], "complete")

    def test_batched_escalation_waits_for_explicit_human_answer(self):
        self.init([self.task(requests=[
            {"question": "Switch model?", "recommendation": "No; keep the zero-cost fake."},
            {"question": "Hire a reviewer?", "recommendation": "No; the checksum is sufficient."},
        ])])
        self.turn()
        self.ring("HELD 7 model and hiring approval")
        held = self.turn()
        self.assertEqual(held["action"], "escalate")
        path = self.root / held["evidence"]
        self.assertIn("Switch model?", path.read_text())
        self.assertIn("Lead recommendation: No;", path.read_text())
        self.assertEqual(self.turn()["action"], "wait-human")
        self.assertEqual(len(self.sent_states), 1)
        self.command("answer", {
            "record_root": str(self.root), "escalation": held["escalation"],
            "by": "fixture-human", "decision": "continue",
            "answer": "Keep existing models and roster; continue original scope.",
        })
        resumed = self.turn()
        self.assertEqual(resumed["action"], "human-answer")
        self.assertIn("fixture-human", path.read_text())
        self.assertIn("Keep existing models", (self.root / "answers/7-human.md").read_text())
        self.assertEqual(len(self.sent_states), 1, "answers use files, never type into blocked panes")

    def test_tier_zero_refuses_before_any_send(self):
        self.init([self.task(planned_commands=["git push origin main --force"])])
        result = self.turn()
        self.assertEqual(result["action"], "compliance-refused")
        self.assertIn("tier-0 violation", result["reason"])
        self.assertEqual(self.sent_states, [])
        self.assertFalse((self.root / "tasks/7.md").exists())
        self.assertIn("push-force", (self.root / "compliance-log.jsonl").read_text())

    def test_receipt_on_disk_survives_missed_doorbell(self):
        self.init()
        self.turn()
        self.receipt()
        self.assertEqual(self.turn()["action"], "accept")
        self.assertEqual(len(self.sent_states), 1)

    def test_claim_copied_from_the_generated_brief_is_accepted_at_the_trusted_digest(self):
        self.init()
        self.turn()
        path = self.root / "tasks/7.md"
        check = next(line for line in path.read_text().splitlines()
                     if line.startswith("- greeting: ")).removeprefix("- greeting: ")
        sidecar = self.root / "tasks/7/result.txt"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_bytes(b"hello\n")
        with path.open("a") as stream:
            stream.write(f"\n## Return — attempt 7\n\nCloses: 7\n\n### Result\n{sidecar}\n\n"
                         f"### Claims\n- greeting: passed ({check})\n\n"
                         f"### Evidence\n{sidecar}\n\n### Sidecars\n- tasks/7/result.txt\n")
        self.assertEqual(self.turn()["action"], "accept")

    def test_malformed_receipt_cannot_be_accepted(self):
        self.init()
        self.turn()
        with (self.root / "tasks/7.md").open("a") as stream:
            stream.write("\n## Return\nCloses: 7\n### Result\nlooks done\n")
        self.ring("DONE 7 tasks/7.md")
        result = self.turn()
        self.assertEqual(result["action"], "receipt-pending")
        self.assertIn("Claims", result["reason"])
        self.assertEqual(self.turn()["action"], "wait")

    def test_receipt_path_outside_record_is_not_read(self):
        self.init()
        self.turn()
        self.ring("DONE 7 ../private.md")
        result = self.turn()
        self.assertEqual(result["action"], "receipt-refused")
        self.assertIn("inside record", result["reason"])

    def test_reused_pane_identity_refuses_without_typing(self):
        self.init()
        self.turn()
        self.snapshot["agents"][0]["terminal_id"] = "replacement"
        result = self.command("lead", {"record_root": str(self.root)}, expected=1)
        self.assertEqual(result["error"]["code"], "identity_mismatch")
        self.assertEqual(len(self.sent_states), 1)

    def test_unseen_done_is_idle_without_focusing_or_weakening_guard(self):
        self.init()
        self.snapshot["agents"][0]["name"] = None
        self.snapshot["agents"][0]["agent_status"] = "done"
        self.snapshot["panes"][0]["agent_status"] = "done"
        result = self.turn()
        self.assertEqual(result["action"], "dispatch")
        self.assertGreaterEqual(result["dispatch"]["guard"]["empty_read_gap_seconds"], 0.01)
        self.assertFalse(any("focus" in r["method"] for r in self.peer.requests))

    def test_closing_rechecks_artifacts_not_stale_acceptance(self):
        self.init()
        self.turn()
        self.receipt()
        self.assertEqual(self.turn()["action"], "accept")
        (self.root / "tasks/7/result.txt").write_text("changed since acceptance\n")
        result = self.turn()
        self.assertEqual(result["action"], "completion-refused")

    def test_done_with_draft_still_refuses(self):
        self.init()
        self.snapshot["agents"][0]["agent_status"] = "done"
        self.snapshot["panes"][0]["agent_status"] = "done"
        self.screens["scratch:p1"] = "[INPUT]\nprivate draft\n[/INPUT]\n"
        result = self.turn()
        self.assertEqual(result["action"], "refused")
        self.assertIn("draft", result["reason"])
        self.assertEqual(self.sent_states, [])

    def test_second_failed_attempt_stops_without_third_dispatch(self):
        self.init()
        self.turn()
        self.receipt(content=b"wrong\n")
        self.assertEqual(self.turn()["action"], "correct")
        self.turn()
        self.receipt("7.2", content=b"still wrong\n")
        self.assertEqual(self.turn()["action"], "stop")
        # Ticket 12: required work that exhausted its attempts is a durable mission
        # failure, never an endless wait; later turns refuse until a human decides.
        failed = self.turn()
        self.assertEqual(failed["action"], "mission-failed")
        self.assertIn("Task 7.2 (stopped)", (self.root / failed["evidence"]).read_text())
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["outcome"]["status"], "failed")
        refused = self.command("lead", {"record_root": str(self.root)}, expected=1)
        self.assertEqual(refused["error"]["code"], "mission_failed")
        self.assertIn("mission-failed.md", refused["error"]["message"])
        self.assertEqual(len(self.sent_states), 2)

    def test_dispatch_rejects_replacement_between_look_and_guard(self):
        self.init()
        original_reply = self.peer.reply
        snapshots = 0

        def replace_after_look(request):
            nonlocal snapshots
            if request["method"] == "session.snapshot":
                snapshots += 1
                if snapshots == 2:
                    for row in self.snapshot["agents"] + self.snapshot["panes"]:
                        row["terminal_id"] = "replacement-after-look"
            return original_reply(request)

        self.peer.reply = replace_after_look
        result = self.turn()
        self.assertEqual(self.sent_states, [], result)
        self.assertEqual(result["action"], "refused")
        self.assertIn("identity", result["reason"])

    def test_dispatch_pin_is_checked_again_immediately_before_send(self):
        self.init()
        original_reply = self.peer.reply

        def replace_after_preparation(request):
            if request["method"] == "session.snapshot":
                reservations = self.project / "adapter-state/dispatches"
                if list(reservations.glob("*/record.json")):
                    for row in self.snapshot["agents"] + self.snapshot["panes"]:
                        row["terminal_id"] = "replacement-after-guard"
            return original_reply(request)

        self.peer.reply = replace_after_preparation
        result = self.turn()
        self.assertEqual(self.sent_states, [], result)
        # The adapter conservatively retains an id reserved before a failed submission.
        self.assertEqual(result["action"], "uncertain")
        reservations = list((self.project / "adapter-state/dispatches").glob("*/record.json"))
        self.assertEqual(len(reservations), 1)
        self.assertIn("identity", json.loads(reservations[0].read_text())["error"])

    def test_brief_receipt_example_is_not_a_member_return(self):
        digest = hashlib.sha256(b"hello\n").hexdigest()
        example = (f"Stop after two attempts. Example only:\n```markdown\n"
                   f"## Return\nCloses: 7\n### Result\nhello\n### Claims\n"
                   f"- greeting: passed (sha256 {digest})\n### Evidence\n"
                   "tasks/7/result.txt\n```")
        self.init([self.task(stop_rule=example)])
        self.turn()
        path = self.root / "tasks/7.md"
        original = path.read_bytes()
        (self.root / "tasks/7/result.txt").write_bytes(b"hello\n")
        result = self.turn()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(result["action"], "wait", result)
        self.ring("DONE 7 tasks/7.md")
        self.assertNotEqual(self.turn()["action"], "accept")
        self.receipt()
        self.assertEqual(self.turn()["action"], "accept")
        self.assertEqual(len(self.sent_states), 1)

    def test_partial_return_retries_changed_revision_without_redispatch(self):
        self.init()
        self.turn()
        path = self.root / "tasks/7.md"
        with path.open("a") as stream:
            stream.write("\n## Return\nCloses: 7\n")
        first = self.turn()
        self.assertEqual(first["action"], "receipt-pending")
        self.assertEqual(self.turn()["action"], "wait")
        (self.root / "tasks/7/result.txt").write_bytes(b"hello\n")
        digest = hashlib.sha256(b"hello\n").hexdigest()
        with path.open("a") as stream:
            stream.write(f"\n### Result\nhello\n### Claims\n"
                         f"- greeting: passed (sha256 {digest})\n"
                         "### Evidence\ntasks/7/result.txt\n")
        self.ring("DONE 7 tasks/7.md")
        self.assertEqual(self.turn()["action"], "accept")
        self.assertEqual(len(self.sent_states), 1)

    def test_partial_return_finishes_without_another_doorbell(self):
        self.init()
        self.turn()
        path = self.root / "tasks/7.md"
        with path.open("a") as stream:
            stream.write("\n## Return\nCloses: 7\n")
        self.ring("DONE 7 tasks/7.md")
        self.assertEqual(self.turn()["action"], "receipt-pending")
        self.assertEqual(self.turn()["action"], "wait")
        (self.root / "tasks/7/result.txt").write_bytes(b"hello\n")
        digest = hashlib.sha256(b"hello\n").hexdigest()
        with path.open("a") as stream:
            stream.write(f"\n### Result\nhello\n### Claims\n"
                         f"- greeting: passed (sha256 {digest})\n"
                         "### Evidence\ntasks/7/result.txt\n")
        self.screens["scratch:p1"] = "[INPUT]\n\n[/INPUT]\n"
        result = self.turn()
        self.assertEqual(result["action"], "accept")
        self.assertEqual(result["candidates"][0]["source"], "disk")
        self.assertEqual(len(self.sent_states), 1)

    def test_changed_lead_prefix_is_not_a_retryable_partial_return(self):
        self.init()
        self.turn()
        path = self.receipt()
        path.write_text(path.read_text().replace("## Stop rule", "## Changed rule", 1))
        result = self.turn()
        self.assertEqual(result["action"], "receipt-refused")
        self.assertIn("lead-owned brief", result["reason"])
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["tasks"]["7"]["status"], "review-refused")
        # Round 3 (R-2): a refused required receipt is a durable mission failure.
        self.assertEqual(self.turn()["action"], "mission-failed")
        self.assertEqual(len(self.sent_states), 1)

    def test_receipt_suffix_cannot_close_another_task_alongside_active_task(self):
        self.init()
        self.turn()
        path = self.receipt()
        text = path.read_text()
        suffix = text[text.index("\n## Return — attempt 7"):]
        with path.open("a") as stream:
            stream.write(suffix.replace("attempt 7", "attempt 8").replace("Closes: 7", "Closes: 8"))
        result = self.turn()
        self.assertEqual(result["action"], "receipt-refused")
        self.assertIn("exactly this attempt", result["reason"])

    def test_escalation_preserves_actual_help_and_held_with_configured_questions(self):
        self.add_member("beta", "scratch:p2")
        requests = [{"question": "Switch model?", "recommendation": "Keep existing models."}]
        self.init([self.task(value=20, requests=requests),
                   self.task("8", "beta", requests=requests)])
        self.turn()
        self.turn()
        help_detail = "May I delete unexpected private records?"
        held_detail = "Publish private records to an external service?"
        self.ring("HELP 7 " + help_detail)
        self.ring("HELD 8 " + held_detail, "scratch:p2")
        result = self.turn()
        text = (self.root / result["evidence"]).read_text()
        self.assertIn(help_detail, text)
        self.assertIn(held_detail, text)
        self.assertIn("Switch model?", text)
        self.assertIn("Keep existing models.", text)
        self.assertEqual(self.turn()["action"], "wait-human")
        self.assertEqual(len(self.sent_states), 2)

    def test_late_rendered_help_is_read_without_state_sequence_change(self):
        self.init()
        self.turn()
        self.snapshot["agents"][0]["agent_status"] = "blocked"
        self.snapshot["panes"][0]["agent_status"] = "blocked"
        self.snapshot["agents"][0]["state_change_seq"] += 1
        self.assertEqual(self.turn()["action"], "wait")
        self.screens["scratch:p1"] = "HELP 7 which greeting\n[INPUT]\n\n[/INPUT]\n"
        sequence = self.snapshot["agents"][0]["state_change_seq"]
        start = len(self.peer.requests)
        self.assertEqual(self.turn()["action"], "answer-help")
        reads = [r for r in self.peer.requests[start:] if r["method"] == "pane.read"]
        self.assertEqual(len(reads), 1, "one bounded passive reread per member per turn")
        self.assertEqual(reads[0]["params"]["source"], "visible")
        self.assertEqual(self.snapshot["agents"][0]["state_change_seq"], sequence)
        self.assertEqual(self.turn()["action"], "wait", "do not answer the same HELP twice")
        self.assertEqual(len(self.sent_states), 1)

    def test_misfiled_human_answer_cannot_release_escalation(self):
        self.init()
        self.turn()
        self.ring("HELD 7 model approval")
        held = self.turn()
        path = self.root / "human-answers/1.json"
        path.parent.mkdir()
        response = {"escalation": "999", "by": "human", "decision": "continue",
                    "answer": "Keep current models."}
        path.write_text(json.dumps(response))
        result = self.command("lead", {"record_root": str(self.root)}, expected=1)
        self.assertEqual(result["error"]["code"], "invalid_answer")
        self.assertIn("escalation", result["error"]["message"])
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["escalations"][0]["status"], "waiting")
        self.assertEqual(state["tasks"]["7"]["status"], "held")
        self.assertFalse((self.root / "answers/7-human.md").exists())
        response["escalation"] = held["escalation"]
        path.write_text(json.dumps(response))
        self.assertEqual(self.turn()["action"], "human-answer")
        self.assertEqual(len(self.sent_states), 1)

    def test_human_answer_file_requires_closed_typed_schema(self):
        self.init()
        self.turn()
        self.ring("HELD 7 model approval")
        self.turn()
        path = self.root / "human-answers/1.json"
        path.parent.mkdir()
        valid = {"escalation": "1", "by": "human", "decision": "continue", "answer": "Keep models."}
        invalid = [[], {**valid, "escalation": 1}, {**valid, "by": True},
                   {**valid, "answer": ["approve"]}, {**valid, "decision": {}},
                   {**valid, "unknown": True}, {k: v for k, v in valid.items() if k != "by"}]
        for response in invalid:
            with self.subTest(response=response):
                path.write_text(json.dumps(response))
                result = self.command("lead", {"record_root": str(self.root)}, expected=1)
                self.assertEqual(result["error"]["code"], "invalid_answer")
                state = json.loads((self.root / "lead-state.json").read_text())
                self.assertEqual(state["escalations"][0]["status"], "waiting")
                self.assertEqual(state["tasks"]["7"]["status"], "held")
                self.assertFalse((self.root / "answers/7-human.md").exists())
        path.write_text(json.dumps(valid))
        self.assertEqual(self.turn()["action"], "human-answer")

    def refuse_init(self, tasks):
        return self.command("init", {
            "record_root": str(self.root), "project_root": str(self.project),
            "workspace_id": "scratch", "lead_pane_id": "scratch:lead",
            "mission": "All required greetings independently checked.",
            "members": [{"name": a["name"], "pane_id": a["pane_id"],
                         "input_box": {"agent": "fake", "start": "[INPUT]", "end": "[/INPUT]"}}
                        for a in self.snapshot["agents"]],
            "tasks": tasks,
        }, expected=1)["error"]

    def test_self_dependency_is_refused_at_init(self):
        # Ticket 11: a task that waits on itself can never become ready.
        error = self.refuse_init([self.task(after=["7"])])
        self.assertIn("cannot depend on itself", error["message"])
        self.assertFalse((self.root / "lead-state.json").exists())

    def test_dependency_cycle_is_refused_at_init(self):
        # Ticket 11: 7 -> 8 -> 7 passes the dependency-existence check but is a cycle.
        error = self.refuse_init([self.task(after=["8"]), self.task("8", after=["7"])])
        self.assertIn("acyclic", error["message"])
        self.assertFalse((self.root / "lead-state.json").exists())

    def test_dependency_chain_is_accepted(self):
        # Control: the same validation accepts a genuine chain.
        self.init([self.task(value=30), self.task("8", after=["7"])])
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["tasks"]["8"]["after"], ["7"])
        self.assertEqual(self.turn()["task"], "7")

    def test_stopped_ring_fails_the_mission_durably(self):
        # Ticket 12: required work ringing STOPPED is a terminal, evidenced failure —
        # never another wait that quietly re-dispatches later.
        self.init()
        self.turn()
        self.ring("STOPPED 7 auth is unreachable")
        self.assertEqual(self.turn()["action"], "stop")
        failed = self.turn()
        self.assertEqual(failed["action"], "mission-failed")
        self.assertIn("Task 7 (stopped)", (self.root / "mission-failed.md").read_text())
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["outcome"], {"status": "failed", "evidence": "mission-failed.md"})
        refused = self.command("lead", {"record_root": str(self.root)}, expected=1)
        self.assertEqual(refused["error"]["code"], "mission_failed")
        self.assertIn("mission-failed.md", refused["error"]["message"])

    def test_optional_stop_does_not_fail_the_mission(self):
        # Ticket 12: the durable failure outcome is reserved for required work.
        self.add_member("beta", "scratch:p2")
        self.init([self.task(value=30), self.task("8", "beta", required=False)])
        self.turn()
        self.turn()
        self.ring("STOPPED 8 skipping the optional extra", pane="scratch:p2")
        self.receipt("7")
        self.ring("DONE 7 tasks/7.md")
        actions = []
        for _ in range(4):
            actions.append(self.turn()["action"])
            if actions[-1] == "complete":
                break
        self.assertEqual(actions[-1], "complete")
        self.assertIn("stop", actions)
        self.assertNotIn("mission-failed", actions)
        self.assertFalse((self.root / "mission-failed.md").exists())

    def test_matt_init_refuses_incomplete_contract_before_creating_record(self):
        error = self.refuse_init([self.task(workflow={"methodology": "matt"})])
        self.assertEqual(error["code"], "schema_invalid")
        self.assertFalse(self.root.exists())

    def test_matt_init_requires_absolute_authoritative_state(self):
        workflow = self.matt_workflow()
        workflow["state"] = "workflow.md"
        result = self.refuse_init([self.task(workflow=workflow)])
        self.assertEqual(result["code"], "schema_invalid")
        self.assertFalse(self.root.exists())

    def parent_record(self, finished=False, snapshot=None, loads=True):
        """The lead's own authoritative parent note, checked by the existing validator."""
        pool = Path.home() / ".agents/skills"
        lines = ["# Parent mission", "", "## Workflow", "Methodology: matt", "Executor: lead",
                 "Route: research", "Phase: investigate", "Next gate: checked worker receipt",
                 "Start: sha256:" + "b" * 64, "DDD: n/a: local fixture", "UX: n/a: no changed journey"]
        for name in ("engineering-workflow", "ask-matt"):
            body = pool / name / "SKILL.md"
            lines.append(f"Procedure: {body}")
            if loads:
                lines.append(f"Loaded: {body} | lead: sha256:"
                             f"{hashlib.sha256(body.read_bytes()).hexdigest()} fixture lead read")
        if snapshot:
            lines.append("Snapshot: " + snapshot)
        if finished:
            lines.append("Check: greeting | passed | fixture receipt accepted at final digest")
        mark = "x" if finished else " "
        lines += ["", "## Done means", "- greeting: worker return accepted at the agreed digest", "",
                  "## Phase checklist", "- [x] Context: source inspected",
                  # the workflow map's research steps (ticket 04): done before the review gate, all but Report at accept
                  "- [x] Scope: questions named", "- [x] Source: plan made", "- [x] Investigate: sources read",
                  "- [x] Synthesize: findings written", f"- [{mark}] Review: claims checked",
                  f"- [{mark}] Verify: receipt matches", f"- [{mark}] Investigation: checked return required",
                  "- [ ] Report", ""]
        (self.project / "workflow.md").write_text("\n".join(lines))

    def matt_workflow(self):
        state = self.project / "workflow.md"
        self.parent_record()
        pool = Path.home() / ".agents/skills"
        return {"methodology": "matt", "phase": "investigate", "route": "research",
                "next_gate": "Source-backed receipt with current reads",
                "start": "sha256:" + "a" * 64, "ddd": "n/a: local fixture",
                "ux": "n/a: no changed journey", "state": str(state),
                "skills": [str(pool / name / "SKILL.md")
                           for name in ("engineering-workflow", "ask-matt", "research")]}

    def accepted_grilling(self, name, scope, decisions):
        """Grilling evidence whose design decisions rest on a closed griller task from another owner."""
        pool = Path.home() / ".agents/skills"
        bodies = [(pool / skill / "SKILL.md").resolve() for skill in ("engineering-workflow", "ask-matt", "grilling")]
        griller = self.project / "griller.md"
        evidence = self.project / name
        design = hashlib.sha256(f"## Design decisions\n{decisions}\n".encode()).hexdigest()
        griller.write_text(
            "---\ntask: 2\nowner: griller\nlatitude: look\nreturn: griller.md\n---\n# Grill the plan\n"
            "## Why\nThe plan needs an independent interview.\n## Outcome\nA plan grilled to an empty frontier.\n"
            "## Done means\n- findings: the plan grilled to an empty frontier\n## Stop rule\nOne pass.\n"
            "\n## Workflow\nMethodology: matt\nExecutor: griller\nRoute: research\nPhase: investigate\n"
            "Next gate: frontier empty\nStart: sha256:" + "c" * 64 + "\nDDD: n/a: local fixture\n"
            "UX: n/a: no changed journey\n" + "".join(f"Procedure: {body}\n" for body in bodies) +
            "\n## Phase checklist\n- [x] Scope: plan read\n- [ ] Investigate: rounds pending\n"
            f"\n## Return\nCloses: 2\n### Result\nGrilled the plan.\nPlan path: {evidence}\nDesign digest: sha256:{design}\n"
            "Frontier: empty\n"
            "### Claims\n- findings: passed (frontier recomputed after the last answer)\n### Evidence\n" +
            "".join(f"Loaded: {body} | griller: sha256:{hashlib.sha256(body.read_bytes()).hexdigest()} "
                    "fixture actual body read\n" for body in bodies))
        evidence.write_text('## Accepted scope\nAccepted: "approved fixture ticket" | fixture-ticket.md\n'
                            f"{scope}\n## Design decisions\n"
                            f"Griller: sha256:{hashlib.sha256(griller.read_bytes()).hexdigest()} | {griller}\n"
                            f"{decisions}\n")
        return evidence

    def test_matt_docs_only_exception_reaches_the_existing_brief_gate(self):
        workflow = self.matt_workflow()
        workflow.update(route="build", phase="implement", implement="n/a: docs-only: static documentation correction")
        workflow["skills"] = workflow["skills"][:2]
        scope = self.accepted_grilling("accepted.md", "Correct the documentation.",
                                       "Keep the existing interface unchanged.")
        workflow["grilling"] = "accepted: sha256:" + hashlib.sha256(scope.read_bytes()).hexdigest() + " | " + str(scope)
        self.init([self.task(kind="implementation", workflow=workflow)])
        self.assertEqual(self.turn()["action"], "dispatch")
        text = (self.root / "tasks/7.md").read_text()
        self.assertIn("Implement: n/a: docs-only:", text)
        self.assertIn("Grilling: " + workflow["grilling"], text)

    def test_matt_build_with_a_plan_only_the_lead_wrote_refuses_before_record_creation(self):
        workflow = self.matt_workflow()
        workflow.update(route="build", phase="implement", implement="n/a: docs-only: static correction")
        workflow["skills"] = workflow["skills"][:2]
        plan = self.project / "lead-plan.md"
        plan.write_text('## Accepted scope\nAccepted: "approved fixture ticket" | fixture-ticket.md\n'
                        "Correct the documentation.\n## Design decisions\nKeep the existing interface unchanged.\n")
        workflow["grilling"] = "accepted: sha256:" + hashlib.sha256(plan.read_bytes()).hexdigest() + " | " + str(plan)
        error = self.refuse_init([self.task(kind="implementation", workflow=workflow)])
        self.assertEqual(error["code"], "contract_invalid")
        self.assertIn("needs a Griller:", error["message"])
        self.assertFalse(self.root.exists())

    def test_matt_build_without_accepted_decisions_refuses_before_record_creation(self):
        workflow = self.matt_workflow()
        workflow.update(route="build", phase="implement", implement="n/a: docs-only: static correction")
        workflow["skills"] = workflow["skills"][:2]
        error = self.refuse_init([self.task(kind="implementation", workflow=workflow)])
        self.assertEqual(error["code"], "contract_invalid")
        self.assertIn("Grilling", error["message"])
        self.assertFalse(self.root.exists())

    def build_workflow(self, **fields):
        """A build-route Matt workflow whose Grilling evidence rests on a griller, plus any new Workflow fields."""
        workflow = self.matt_workflow()
        workflow.update(route="build", phase="implement", implement="n/a: docs-only: static correction")
        workflow["skills"] = workflow["skills"][:2]
        scope = self.accepted_grilling("accepted.md", "Correct the documentation.",
                                       "Keep the existing interface unchanged.")
        workflow["grilling"] = "accepted: sha256:" + hashlib.sha256(scope.read_bytes()).hexdigest() + " | " + str(scope)
        workflow.update(fields)
        return workflow

    def brief_check(self, path):
        validator = CLI.parents[2] / "skills/team-lead/scripts/validate_contracts.py"
        return subprocess.run([sys.executable, "-B", str(validator), "brief", str(path), "--matt"],
                              capture_output=True, text=True)

    def test_matt_workflow_forwards_the_route_decision_and_the_cut_into_the_brief(self):
        workflow = self.build_workflow(
            route_decision="multi-session: no; reason: one documentation correction needs no spec and tickets",
            cut=[f'retro | "skip the retrospective for this fixture" | {self.session_log}',
                 'review | "skip the review, I read it myself" | fixture-session.log line 40'])
        self.init([self.task(kind="implementation", workflow=workflow)])
        self.assertEqual(self.turn()["action"], "dispatch")
        path = self.root / "tasks/7.md"
        text = path.read_text()
        self.assertIn("\nRoute decision: " + workflow["route_decision"] + "\n", text)
        for cut in workflow["cut"]:
            self.assertIn("\nCut: " + cut + "\n", text)
        checked = self.brief_check(path)
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_matt_workflow_forwards_a_pinned_multi_session_route_decision(self):
        spec, tickets = self.project / "spec.md", self.project / "tickets.md"
        spec.write_text("# Spec\nCorrect the documentation.\n")
        tickets.write_text("# Tickets\n01: correct the documentation.\n")
        pin = lambda path: "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() + " | " + str(path)
        workflow = self.build_workflow(route_decision=f"multi-session: yes; spec: {pin(spec)}; tickets: {pin(tickets)}")
        self.init([self.task(kind="implementation", workflow=workflow)])
        self.assertEqual(self.turn()["action"], "dispatch")
        path = self.root / "tasks/7.md"
        self.assertIn("\nRoute decision: " + workflow["route_decision"] + "\n", path.read_text())
        checked = self.brief_check(path)
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_matt_workflow_refuses_each_bad_route_decision_and_cut_before_record_creation(self):
        spec, tickets = self.project / "spec.md", self.project / "tickets.md"
        spec.write_text("# Spec\nCorrect the documentation.\n")
        tickets.write_text("# Tickets\n01: correct the documentation.\n")
        pin = lambda path: "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() + " | " + str(path)
        stale = f"multi-session: yes; spec: sha256:{'0' * 64} | {spec}; tickets: {pin(tickets)}"
        cases = {
            "no without a reason": ({"route_decision": "multi-session: no; reason: TBD"}, "needs a reason"),
            "yes with an unpinned spec": ({"route_decision": f"multi-session: yes; spec: {spec}; tickets: {pin(tickets)}"},
                                          "unpinned"),
            "yes with a spec changed since the pin": ({"route_decision": stale}, "changed since the decision pinned it"),
            "not a branch": ({"route_decision": "maybe"}, "Route decision"),
            "cut without a source": ({"cut": 'retro | "the human said skip it"'}, "Cut needs the human's quote"),
            "cut with a placeholder quote": ({"cut": "retro | TBD | fixture-session.log"}, "Cut needs the human's quote"),
            "cut of a step the map does not require": ({"cut": f'deploy | "ship it" | {self.session_log}'},
                                                       "not a step the workflow map requires"),
        }
        for name, (fields, expected) in cases.items():
            with self.subTest(name):
                workflow = self.build_workflow(**fields)
                error = self.refuse_init([self.task(kind="implementation", workflow=workflow)])
                self.assertEqual(error["code"], "contract_invalid")
                self.assertIn(expected, error["message"])
                self.assertFalse(self.root.exists())

    def test_matt_workflow_refuses_malformed_route_decision_and_cut_values(self):
        line = 'retro | "skip" | log'
        cases = {
            "route decision is not text": ({"route_decision": ["multi-session: no; reason: x"]}, "missing_target"),
            "route decision is blank": ({"route_decision": " "}, "missing_target"),
            "route decision carries a second line": (
                {"route_decision": "multi-session: no; reason: small\nCut: review | \"skip\" | log"}, "schema_invalid"),
            "cut is not text or a list of text": ({"cut": 3}, "schema_invalid"),
            "cut is an empty list": ({"cut": []}, "schema_invalid"),
            "a cut entry is not text": ({"cut": [line, 5]}, "missing_target"),
            "a cut entry carries a second line": ({"cut": line + "\nCut: review | \"skip\" | log"}, "schema_invalid"),
        }
        for name, (fields, code) in cases.items():
            with self.subTest(name):
                error = self.refuse_init([self.task(kind="implementation", workflow=self.build_workflow(**fields))])
                self.assertEqual(error["code"], code)
                self.assertNotIn("unknown fields", error["message"], "the key is known; its value is what is wrong")
                self.assertFalse(self.root.exists())

    def test_matt_workflow_refuses_a_second_line_in_the_grilling_value(self):
        grilling = self.build_workflow()["grilling"]
        forged = {"a second Workflow key": "\nRoute decision: multi-session: no; reason: forged by the grilling value",
                  "a forged Cut": f'\nCut: review | "skip the review" | {self.session_log}',
                  "a carriage return": '\rCut: review | "skip the review" | log'}
        for name, extra in forged.items():
            with self.subTest(name):
                error = self.refuse_init([self.task(kind="implementation",
                                                    workflow=self.build_workflow(grilling=grilling + extra))])
                self.assertEqual(error["code"], "schema_invalid")
                self.assertIn("workflow grilling must be a single line", error["message"])
                self.assertFalse(self.root.exists())

    def test_non_matt_workflow_does_not_take_the_route_decision_or_the_cut(self):
        for field, value in (("route_decision", "multi-session: no; reason: small"), ("cut", 'retro | "skip" | log')):
            with self.subTest(field):
                workflow = {"methodology": "cc10x", "phase": "implementation", field: value}
                error = self.refuse_init([self.task(kind="implementation", workflow=workflow)])
                self.assertEqual(error["code"], "schema_invalid")
                self.assertIn("unknown fields", error["message"])
                self.assertFalse(self.root.exists())

    def edit_parent(self, old, new):
        record = self.project / "workflow.md"
        text = record.read_text()
        self.assertIn(old, text)
        record.write_text(text.replace(old, new, 1))

    def test_parent_entry_gate_refuses_a_skipped_step_until_the_human_cut_is_recorded(self):
        self.init([self.task(kind="research", workflow=self.matt_workflow())])
        self.edit_parent("- [x] Source: plan made\n", "")
        error = self.command("lead", {"record_root": str(self.root), "wait_seconds": 0.03}, expected=1)["error"]
        self.assertEqual(error["code"], "parent_gate")
        self.assertIn("missing the required step 'source'", error["message"])
        self.assertEqual(self.sent_states, [])
        self.assertFalse((self.root / "tasks/7.md").exists())
        self.edit_parent("UX: n/a: no changed journey\n", "UX: n/a: no changed journey\n"
                         f'Cut: source | "skip the source plan, I have the sources" | {self.session_log}\n')
        self.assertEqual(self.turn()["action"], "dispatch")

    def test_parent_accept_gate_holds_a_missing_step_and_takes_the_human_cut(self):
        self.init([self.task(kind="research", workflow=self.matt_workflow())])
        self.turn()
        path = self.receipt()
        with path.open("a") as stream:
            for value in self.matt_workflow()["skills"]:
                digest = hashlib.sha256(Path(value).read_bytes()).hexdigest()
                stream.write(f"Loaded: {value} | alpha: sha256:{digest} fixture actual body read\n")
        self.assertEqual(self.turn()["action"], "accept")
        self.parent_record(finished=True)
        self.edit_parent("- [x] Verify: receipt matches\n", "")
        self.assertEqual(self.turn()["action"], "completion-refused")
        parent = json.loads((self.root / "closing-checks.json").read_text())[-1]
        self.assertEqual(parent["gate"], "accept")
        self.assertTrue(any("missing the required step 'verify'" in e for e in parent["errors"]), parent["errors"])
        self.edit_parent("UX: n/a: no changed journey\n", "UX: n/a: no changed journey\n"
                         'Cut: verify | "the receipt check is enough, skip verify" | fixture-session.log line 9\n')
        self.assertEqual(self.turn()["action"], "complete")

    def test_parent_entry_gate_refuses_a_read_stamped_after_the_phase_start_check(self):
        self.init([self.task(kind="research", workflow=self.matt_workflow())])
        start = "Check: start investigate | passed | gate ran at:2026-10-17T10:00:00Z\n"
        record = self.project / "workflow.md"
        text = record.read_text().replace(" fixture lead read\n", " fixture lead read at:2026-10-17T10:05:00Z\n")
        record.write_text(text.replace("UX: n/a: no changed journey\n", "UX: n/a: no changed journey\n" + start))
        error = self.command("lead", {"record_root": str(self.root), "wait_seconds": 0.03}, expected=1)["error"]
        self.assertEqual(error["code"], "parent_gate")
        self.assertIn("start Check of step 'investigate'", error["message"])
        self.assertEqual(self.sent_states, [])
        record.write_text(record.read_text().replace("at:2026-10-17T10:05:00Z", "at:2026-10-17T09:55:00Z"))
        self.assertEqual(self.turn()["action"], "dispatch")

    def test_parent_entry_gate_times_an_aliased_read_by_the_body_it_resolves_to(self):
        self.init([self.task(kind="research", workflow=self.matt_workflow())])
        body = Path.home() / ".agents/skills/engineering-workflow/SKILL.md"
        start = "UX: n/a: no changed journey\nCheck: start investigate | passed | gate ran at:2026-10-17T10:00:00Z\n"
        record = self.project / "workflow.md"

        def alias_read(name, stamp):
            alias = self.project / name
            alias.parent.mkdir(exist_ok=True)
            if not alias.is_symlink():
                alias.symlink_to(body)
            self.parent_record()
            lines = [f"{line.replace(str(body), str(alias))} at:{stamp}" if line.startswith(f"Loaded: {body} ") else line
                     for line in record.read_text().splitlines()]
            record.write_text("\n".join(lines).replace("UX: n/a: no changed journey\n", start) + "\n")

        # An alias named for a skill whose step has no start Check must not leave the late read unheld.
        for name in ("tdd/SKILL.md", "renamed.md"):
            with self.subTest(alias=name):
                alias_read(name, "2026-10-17T10:05:00Z")
                error = self.command("lead", {"record_root": str(self.root), "wait_seconds": 0.03}, expected=1)["error"]
                self.assertEqual(error["code"], "parent_gate")
                self.assertIn("start Check of step 'investigate'", error["message"])
                self.assertEqual(self.sent_states, [])
        alias_read("tdd/SKILL.md", "2026-10-17T09:55:00Z")
        self.assertEqual(self.turn()["action"], "dispatch")

    def test_worker_receipt_with_a_read_stamped_after_its_start_check_is_held(self):
        for stamp, action in (("2026-10-17T10:05:00Z", "receipt-pending"), ("2026-10-17T09:55:00Z", "accept")):
            with self.subTest(read_at=stamp):
                self.tearDown()
                self.setUp()
                workflow = self.matt_workflow()
                self.init([self.task(kind="research", workflow=workflow)])
                self.turn()
                path = self.receipt()
                with path.open("a") as stream:
                    stream.write("Check: start investigate | passed | gate ran at:2026-10-17T10:00:00Z\n")
                    for value in workflow["skills"]:
                        digest = hashlib.sha256(Path(value).read_bytes()).hexdigest()
                        stream.write(f"Loaded: {value} | alpha: sha256:{digest} fixture actual body read at:{stamp}\n")
                held = self.turn()
                self.assertEqual(held["action"], action)
                if action == "receipt-pending":
                    self.assertIn("start Check of step 'investigate'", held["reason"])

    def cut_source(self, *quotes):
        """The human's session log with `quotes` added to the ones every fixture holds."""
        self.session_log.write_text(self.session_log.read_text() + "".join(f'"{quote}"\n' for quote in quotes))
        return self.session_log

    def test_a_worker_dispatched_under_the_humans_cut_is_accepted_when_the_cut_lifts_its_minimum(self):
        cases = {
            "cut of grilling, no Grilling line": ("grilling", "no interview needed for this fixture", ("grilling",)),
            "cut of implement, no implement exemption": ("implement", "skip implement and tdd for this fixture",
                                                         ("implement",)),
            "a cut that lifts nothing for the worker": ("retro", "skip the retrospective for this fixture", ()),
        }
        for name, (step, quote, drop) in cases.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                log = self.cut_source("no interview needed for this fixture", "skip implement and tdd for this fixture")
                workflow = self.build_workflow(cut=f'{step} | "{quote}" | {log}')
                for key in drop:
                    del workflow[key]
                self.init([self.task(kind="implementation", workflow=workflow)])
                self.assertEqual(self.turn()["action"], "dispatch")
                path = self.receipt()
                with path.open("a") as stream:
                    for value in workflow["skills"]:
                        digest = hashlib.sha256(Path(value).read_bytes()).hexdigest()
                        stream.write(f"Loaded: {value} | alpha: sha256:{digest} fixture actual body read\n")
                held = self.turn()
                self.assertEqual(held["action"], "accept", held)

    def test_a_relative_cut_source_resolves_from_the_folder_of_the_file_that_holds_the_cut_line(self):
        # The parent State sits in self.project beside fixture-session.log; the brief is written to <root>/tasks/.
        error = self.refuse_init([self.task(kind="implementation", workflow=self.build_workflow(
            cut='retro | "skip the retrospective for this fixture" | fixture-session.log'))])
        self.assertEqual(error["code"], "contract_invalid")
        self.assertRegex(error["message"], r"Cut source fixture-session\.log is unavailable at \S*/tasks/fixture-session\.log")
        self.assertFalse(self.root.exists())
        self.init([self.task(kind="research", workflow=self.matt_workflow())])
        self.edit_parent("- [x] Source: plan made\n", "")
        self.edit_parent("UX: n/a: no changed journey\n", "UX: n/a: no changed journey\n"
                         'Cut: source | "skip the source plan, I have the sources" | fixture-session.log\n')
        self.assertEqual(self.turn()["action"], "dispatch")

    def test_a_cut_source_over_the_one_size_limit_is_refused_by_the_parent_gate_and_the_cli_alike(self):
        validator = CLI.parents[2] / "skills/team-lead/scripts/validate_contracts.py"
        limit = 2 * 1024 * 1024
        tail = b'\n"skip the source plan, I have the sources"\n'
        for size, refused in ((limit, False), (limit + 1, True)):
            with self.subTest(size=size):
                self.tearDown()
                self.setUp()
                big = self.project / "session.jsonl"
                big.write_bytes(b"x" * (size - len(tail)) + tail)
                self.init([self.task(kind="research", workflow=self.matt_workflow())])
                self.edit_parent("- [x] Source: plan made\n", "")
                self.edit_parent("UX: n/a: no changed journey\n", "UX: n/a: no changed journey\n"
                                 'Cut: source | "skip the source plan, I have the sources" | session.jsonl\n')
                cli = subprocess.run([sys.executable, "-B", str(validator), "workflow", str(self.project / "workflow.md"),
                                      "--gate", "entry"], capture_output=True, text=True)
                if not refused:
                    self.assertEqual(cli.returncode, 0, cli.stderr)
                    self.assertEqual(self.turn()["action"], "dispatch")
                    continue
                error = self.command("lead", {"record_root": str(self.root), "wait_seconds": 0.03}, expected=1)["error"]
                self.assertEqual(error["code"], "parent_gate")
                self.assertEqual(self.sent_states, [])
                sentence = "Cut source session.jsonl is larger than 2097152 bytes"
                self.assertEqual(cli.returncode, 1, cli.stderr)
                self.assertIn(sentence, cli.stderr)
                self.assertIn(sentence, error["message"])

    def test_complete_matt_brief_passes_the_existing_preparation_gate(self):
        self.init([self.task(kind="research", workflow=self.matt_workflow())])
        self.assertEqual(self.turn()["action"], "dispatch")
        path = self.root / "tasks/7.md"
        validator = CLI.parents[2] / "skills/team-lead/scripts/validate_contracts.py"
        checked = subprocess.run([sys.executable, "-B", str(validator), "brief",
                                  str(path), "--matt"], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("Executor: alpha", path.read_text())

    def test_matt_dispatch_delivers_exact_selected_procedure_bodies(self):
        workflow = self.matt_workflow()
        self.init([self.task(kind="research", workflow=workflow)])
        self.assertEqual(self.turn()["action"], "dispatch")
        manifest = json.loads((self.root / "tasks/7/delivery/manifest.json").read_text())
        self.assertEqual([row["selected"] for row in manifest["procedures"]], workflow["skills"])
        brief = (self.root / "tasks/7.md").read_text()
        self.assertIn("tasks/7/delivery/manifest.json", brief)
        for value, row in zip(workflow["skills"], manifest["procedures"]):
            body = Path(value).read_bytes()
            self.assertEqual(row["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(row["bytes"], len(body))
            self.assertEqual((self.root / row["copy"]).read_bytes(), body)
            self.assertIn(f"{value} | sha256:{row['sha256']} bytes:{len(body)} | {row['copy']}", brief)
        self.assertNotIn("Loaded:", brief, "delivery must not invent worker read records")

    def test_unreadable_selected_procedure_refuses_before_any_send(self):
        for breakage in ("missing", "directory", "oversize"):
            with self.subTest(breakage=breakage):
                self.tearDown()
                self.setUp()
                workflow = self.matt_workflow()
                procedure = self.project / "fixture-procedure.md"
                procedure.write_text("Fixture procedure.\n")
                workflow["skills"].append(str(procedure))
                self.init([self.task(kind="research", workflow=workflow)])
                procedure.unlink()
                if breakage == "directory":
                    procedure.mkdir()
                if breakage == "oversize":
                    procedure.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
                error = self.command("lead", {"record_root": str(self.root), "wait_seconds": 0.03},
                                     expected=1)["error"]
                self.assertEqual(error["code"], "procedure_unavailable")
                self.assertEqual(self.sent_states, [])
                self.assertFalse((self.root / "tasks/7.md").exists())
                self.assertFalse((self.root / "tasks/7/delivery/manifest.json").exists())
                state = json.loads((self.root / "lead-state.json").read_text())
                self.assertEqual(state["tasks"]["7"]["status"], "queued")

    def staged_packet(self, body):
        """Deliver once in-process, as an interrupted dispatch would, and return its rows."""
        sys.path.insert(0, str(CLI.parent))
        import lead
        workflow = self.matt_workflow()
        procedure = self.project / "fixture-procedure.md"
        procedure.write_bytes(body)
        workflow["skills"].append(str(procedure))
        self.init([self.task(kind="research", workflow=workflow)])
        root = self.root.resolve()
        task = json.loads((root / "lead-state.json").read_text())["tasks"]["7"]
        rows, _ = lead.deliver(root, task, root / "tasks/7.md")
        return lead, root, task, rows

    def test_crlf_packet_replays_byte_exact_and_changed_newlines_refuse(self):
        for body, changed in ((b"one\r\ntwo\r\n", b"one\ntwo\n"), (b"one\ntwo\n", b"one\r\ntwo\r\n")):
            with self.subTest(body=body):
                self.tearDown()
                self.setUp()
                lead, root, task, rows = self.staged_packet(body)
                copy = root / rows[-1]["copy"]
                self.assertEqual(copy.read_bytes(), body)
                self.assertEqual(lead.deliver(root, task, root / "tasks/7.md")[0], rows)
                copy.chmod(0o644)
                copy.write_bytes(changed)
                with self.assertRaises(lead.Refusal) as refused:
                    lead.deliver(root, task, root / "tasks/7.md")
                self.assertEqual(refused.exception.code, "delivery_mismatch")

    def test_packet_admitted_at_body_ceilings_replays_unchanged(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        for ceiling in ("bytes", "reads"):
            with self.subTest(ceiling=ceiling):
                self.tearDown()
                self.setUp()
                workflow = self.matt_workflow()
                used = sum(Path(s).stat().st_size for s in workflow["skills"])
                if ceiling == "bytes":
                    left = lead.DELIVERY_LIMIT - used
                    sizes = [lead.PROCEDURE_LIMIT] * (left // lead.PROCEDURE_LIMIT) + [left % lead.PROCEDURE_LIMIT]
                else:
                    sizes = [1] * (128 - len(workflow["skills"]))
                for index, size in enumerate(sizes):
                    body = self.project / f"ceiling-{index}.md"
                    body.write_bytes(b"c" * size)
                    workflow["skills"].append(str(body))
                self.init([self.task(kind="research", workflow=workflow)])
                root = self.root.resolve()
                task = json.loads((root / "lead-state.json").read_text())["tasks"]["7"]
                rows, _ = lead.deliver(root, task, root / "tasks/7.md")
                self.assertEqual(sum(r["bytes"] for r in rows) == lead.DELIVERY_LIMIT, ceiling == "bytes")
                self.assertEqual(len(rows) == 128, ceiling == "reads")
                self.assertEqual(lead.deliver(root, task, root / "tasks/7.md")[0], rows)

    def test_nonregular_or_oversize_packet_replay_refuses_promptly(self):
        for breakage in ("fifo", "oversize"):
            with self.subTest(breakage=breakage):
                self.tearDown()
                self.setUp()
                _, root, _, rows = self.staged_packet(b"fixture\n")
                target = root / ("tasks/7/delivery/manifest.json" if breakage == "fifo" else rows[-1]["copy"])
                target.unlink()
                if breakage == "fifo":
                    os.mkfifo(target)
                else:
                    target.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
                error = self.command("lead", {"record_root": str(self.root), "wait_seconds": 0.03},
                                     expected=1)["error"]
                self.assertEqual(error["code"], "delivery_mismatch")
                self.assertEqual(self.sent_states, [])

    def test_parent_follow_up_reads_are_bounded(self):
        for breakage in ("fifo-procedure", "aggregate", "snapshot"):
            with self.subTest(breakage=breakage):
                self.tearDown()
                self.setUp()
                workflow = self.matt_workflow()
                kind = "research"
                if breakage == "snapshot":
                    # Only the review/accept gates check Snapshot.
                    kind = "review"
                    workflow.update(route="review", phase="review")
                    workflow["skills"] = workflow["skills"][:2] + [
                        str(Path.home() / ".agents/skills/code-review/SKILL.md")]
                self.init([self.task(kind=kind, workflow=workflow)])
                parent = self.project / "workflow.md"
                text = parent.read_text()
                extra = []
                if breakage == "fifo-procedure":
                    fifo = self.project / "fifo-procedure.md"
                    os.mkfifo(fifo)
                    extra = [f"Procedure: {fifo}", f"Loaded: {fifo} | lead: sha256:{'c' * 64} fixture read"]
                if breakage == "aggregate":
                    for index in range(5):
                        body = self.project / f"large-{index}.md"
                        body.write_bytes(b"y" * (1900 * 1024))
                        extra += [f"Procedure: {body}", f"Loaded: {body} | lead: sha256:"
                                  f"{hashlib.sha256(body.read_bytes()).hexdigest()} fixture read"]
                if breakage == "snapshot":
                    artifact = self.project / "large-snapshot.txt"
                    artifact.write_bytes(b"z" * (2 * 1024 * 1024 + 1))
                    extra = ["Snapshot: sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
                             + " | " + str(artifact)]
                parent.write_text(text.replace("UX: n/a: no changed journey\n",
                                               "UX: n/a: no changed journey\n" + "\n".join(extra) + "\n"))
                error = self.command("lead", {"record_root": str(self.root), "wait_seconds": 0.03},
                                     expected=1)["error"]
                self.assertEqual(error["code"], "parent_gate")
                self.assertRegex(error["message"], "bounded|cap")
                self.assertEqual(self.sent_states, [])

    def test_differing_earlier_delivery_packet_refuses_before_any_send(self):
        self.init([self.task(kind="research", workflow=self.matt_workflow())])
        stale = self.root / "tasks/7/delivery/manifest.json"
        stale.parent.mkdir(parents=True)
        stale.write_text('{"attempt": "7", "procedures": []}\n')
        error = self.command("lead", {"record_root": str(self.root), "wait_seconds": 0.03},
                             expected=1)["error"]
        self.assertEqual(error["code"], "delivery_mismatch")
        self.assertEqual(self.sent_states, [])
        self.assertFalse((self.root / "tasks/7.md").exists())

    def test_non_matt_workflow_skills_are_not_delivered(self):
        workflow = {"methodology": "cc10x", "phase": "implementation",
                    "skills": ["~/.agents/skills/tdd/SKILL.md"]}
        self.init([self.task(kind="implementation", workflow=workflow)])
        self.assertEqual(self.turn()["action"], "dispatch")
        self.assertFalse((self.root / "tasks/7/delivery").exists())
        self.assertNotIn("## Delivered procedures", (self.root / "tasks/7.md").read_text())

    def test_matt_receipt_without_current_worker_reads_is_held(self):
        workflow = self.matt_workflow()
        self.init([self.task(kind="research", workflow=workflow)])
        self.turn()
        path = self.receipt()
        self.assertEqual(self.turn()["action"], "receipt-pending")
        self.assertEqual(len(self.sent_states), 1)
        with path.open("a") as stream:
            for value in workflow["skills"]:
                body = Path(value).read_bytes()
                digest = hashlib.sha256(body).hexdigest()
                stream.write(f"Loaded: {value} | alpha: sha256:{digest} fixture actual body read\n")
        self.assertEqual(self.turn()["action"], "accept")
        held = self.turn()
        self.assertEqual(held["action"], "completion-refused", "worker acceptance is not parent completion")
        parent = json.loads((self.root / "closing-checks.json").read_text())[-1]
        self.assertEqual(parent["gate"], "accept")
        self.assertTrue(any("unfinished Phase checklist" in e for e in parent["errors"]))
        self.parent_record(finished=True)
        self.assertEqual(self.turn()["action"], "complete")

    def test_invalid_parent_entry_gate_sends_nothing(self):
        workflow = self.matt_workflow()
        self.init([self.task(kind="research", workflow=workflow)])
        self.parent_record(loads=False)
        error = self.command("lead", {"record_root": str(self.root), "wait_seconds": 0.03},
                             expected=1)["error"]
        self.assertEqual(error["code"], "parent_gate")
        self.assertIn("entry", error["message"])
        self.assertIn("missing Loaded read record", error["message"])
        self.assertEqual(self.sent_states, [])
        self.assertFalse((self.root / "tasks/7.md").exists())
        self.assertFalse((self.root / "tasks/7").exists())
        self.parent_record()
        self.assertEqual(self.turn()["action"], "dispatch")

    def test_review_dispatch_requires_the_parent_review_gate(self):
        workflow = self.matt_workflow()
        pool = Path.home() / ".agents/skills"
        workflow.update(route="review", phase="review")
        workflow["skills"] = workflow["skills"][:2] + [str(pool / "code-review/SKILL.md")]
        self.init([self.task(kind="review", workflow=workflow)])
        error = self.command("lead", {"record_root": str(self.root), "wait_seconds": 0.03},
                             expected=1)["error"]
        self.assertEqual(error["code"], "parent_gate")
        self.assertIn("Snapshot is required", error["message"])
        self.assertEqual(self.sent_states, [])
        artifact = self.project / "reviewed.txt"
        artifact.write_text("pinned review input\n")
        self.parent_record(snapshot="sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
                           + " | " + str(artifact))
        self.assertEqual(self.turn()["action"], "dispatch")

    def test_ask_matt_alias_cannot_bypass_the_preparation_gate(self):
        self.refuse_init([self.task(workflow={"methodology": "ask-matt"})])
        self.assertFalse(self.root.exists())

    def test_matt_init_refuses_missing_phase_checklist_before_writes(self):
        workflow = self.matt_workflow()
        Path(workflow["state"]).write_text("No ordered phases.\n")
        error = self.refuse_init([self.task(workflow=workflow)])
        self.assertEqual(error["code"], "contract_invalid")
        self.assertFalse(self.root.exists())

    def test_changed_procedure_body_holds_matt_acceptance(self):
        workflow = self.matt_workflow()
        procedure = self.project / "fixture-procedure.md"
        procedure.write_text("Original fixture procedure.\n")
        workflow["skills"].append(str(procedure))
        self.init([self.task(kind="research", workflow=workflow)])
        self.turn()
        path = self.receipt()
        with path.open("a") as stream:
            for value in workflow["skills"]:
                digest = hashlib.sha256(Path(value).read_bytes()).hexdigest()
                stream.write(f"Loaded: {value} | alpha: sha256:{digest} fixture actual body read\n")
        procedure.write_text("Changed fixture procedure.\n")
        held = self.turn()
        self.assertEqual(held["action"], "receipt-pending")
        self.assertIn("body changed", held["reason"])
        self.assertEqual(len(self.sent_states), 1)

    def test_brief_carries_kind_and_workflow_selection(self):
        # Ticket 14: the methodology selection travels with the brief so a member's
        # harness default cannot silently replace the parent's workflow.
        workflow = {"methodology": "cc10x", "phase": "implementation",
                    "skills": ["~/.agents/skills/tdd/SKILL.md"],
                    "scheduler": "lead", "integration_owner": "alpha"}
        self.init([self.task(kind="implementation", workflow=workflow)])
        self.turn()
        text = (self.root / "tasks/7.md").read_text()
        self.assertIn("kind: implementation", text)
        self.assertIn("## Workflow", text)
        self.assertIn("Methodology: cc10x", text)
        self.assertIn("Phase: implementation", text)
        self.assertIn("tdd/SKILL.md", text)
        self.assertIn("Scheduler: lead", text)
        self.assertIn("Integration owner: alpha", text)
        self.assertIn("cannot silently replace this workflow", text)

    def test_brief_without_workflow_carries_no_workflow_section(self):
        # Control: unselected methodology adds nothing to the brief.
        self.init()
        self.turn()
        text = (self.root / "tasks/7.md").read_text()
        self.assertNotIn("## Workflow", text)
        self.assertNotIn("kind:", text)

    def test_init_refuses_unknown_kind_and_incomplete_workflow(self):
        error = self.refuse_init([self.task(kind="speculation")])
        self.assertIn("kind must be", error["message"])
        error = self.refuse_init([self.task(workflow={"phase": "implementation"})])
        self.assertIn("methodology", error["message"])

    def test_malformed_kind_is_a_structured_refusal_not_a_traceback(self):
        # Round 3 (S-2): kind=[] is unhashable; set membership crashed before any
        # structured refusal reached the documented JSON interface.
        error = self.refuse_init([self.task(kind=[])])
        self.assertIn("kind must be", error["message"])
        self.assertFalse((self.root / "lead-state.json").exists())

    def test_malformed_workflow_skills_is_refused_at_init(self):
        # Round 3 (S-1/R-3): the guard read "skills" from the task, not the workflow
        # object, so init accepted these values and brief generation later crashed
        # on join() or garbled the required skill paths.
        for skills in ([{}], "bad", 7):
            with self.subTest(skills=skills):
                error = self.refuse_init([self.task(
                    workflow={"methodology": "ask-matt", "skills": skills})])
                self.assertIn("workflow skills must be a list of required skill paths",
                              error["message"])
                self.assertFalse((self.root / "lead-state.json").exists())

    def test_required_receipt_refusal_fails_the_mission_durably(self):
        # Round 3 (R-2): review-refused is a terminal refusal of required work; the
        # turn chain used to fall through to wait forever with no durable outcome.
        self.init()
        self.turn()
        path = self.receipt()
        text = path.read_text()
        suffix = text[text.index("\n## Return — attempt 7"):]
        with path.open("a") as stream:
            stream.write(suffix.replace("Closes: 7", "Closes: 8"))
        self.assertEqual(self.turn()["action"], "receipt-refused")
        failed = self.turn()
        self.assertEqual(failed["action"], "mission-failed")
        self.assertIn("Task 7 (review-refused)", (self.root / "mission-failed.md").read_text())
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["outcome"], {"status": "failed", "evidence": "mission-failed.md"})
        refused = self.command("lead", {"record_root": str(self.root)}, expected=1)
        self.assertEqual(refused["error"]["code"], "mission_failed")

    def test_optional_receipt_refusal_does_not_fail_the_mission(self):
        # Round 3 (R-2) control: the durable failure stays reserved for required work.
        self.add_member("beta", "scratch:p2")
        self.init([self.task(value=30), self.task("8", "beta", required=False)])
        self.turn()
        self.turn()
        path = self.receipt("8")
        text = path.read_text()
        suffix = text[text.index("\n## Return — attempt 8"):]
        with path.open("a") as stream:
            stream.write(suffix.replace("Closes: 8", "Closes: 7"))
        self.ring("DONE 8 tasks/8.md", pane="scratch:p2")
        self.assertEqual(self.turn()["action"], "receipt-refused")
        self.receipt("7")
        self.ring("DONE 7 tasks/7.md")
        actions = []
        for _ in range(4):
            actions.append(self.turn()["action"])
            if actions[-1] == "complete":
                break
        self.assertEqual(actions[-1], "complete")
        self.assertNotIn("mission-failed", actions)
        self.assertFalse((self.root / "mission-failed.md").exists())

    def test_review_refused_optional_task_frees_the_owner_for_required_work(self):
        # An optional task refused at review is terminal for its owner: an
        # independent required task for the same member must dispatch and
        # complete instead of waiting on a busy flag that never clears.
        self.init([self.task("7", required=False), self.task("8")])
        self.assertEqual(self.turn()["task"], "7")
        path = self.receipt("7")
        text = path.read_text()
        suffix = text[text.index("\n## Return — attempt 7"):]
        with path.open("a") as stream:
            stream.write(suffix.replace("Closes: 7", "Closes: 8"))
        self.ring("DONE 7 tasks/7.md")
        self.assertEqual(self.turn()["action"], "receipt-refused")
        redispatch = self.turn()
        self.assertEqual((redispatch["moment"], redispatch["action"]), ("M2", "dispatch"))
        self.assertEqual(redispatch["task"], "8")
        self.receipt("8")
        self.ring("DONE 8 tasks/8.md")
        actions = []
        for _ in range(4):
            actions.append(self.turn()["action"])
            if actions[-1] == "complete":
                break
        self.assertEqual(actions[-1], "complete")
        self.assertNotIn("mission-failed", actions)
        self.assertFalse((self.root / "mission-failed.md").exists())


    VERIFIER = ("import os, sys, time\n"
                "open('verifier-runs', 'a').write(os.getcwd() + '\\n')\n"
                "verdict = open('verdict').read().strip()\n"
                "time.sleep(30) if verdict == 'hang' else sys.exit(int(verdict))\n")

    def test_unreadable_return_is_refused_for_its_task_and_other_work_proceeds(self):
        for kind in ("fifo", "directory", "non-utf-8", "oversize"):
            with self.subTest(kind=kind):
                self.tearDown()
                self.setUp()
                self.init([self.task("7", required=False), self.task("8")])
                self.assertEqual(self.turn()["task"], "7")
                path = self.root / "tasks/7.md"
                if kind in {"fifo", "directory"}:
                    path.unlink()
                    os.mkfifo(path) if kind == "fifo" else path.mkdir()
                else:
                    self.receipt("7")
                    with path.open("ab") as stream:
                        stream.write(b"\xff\n" if kind == "non-utf-8" else b"x" * (2 * 1024 * 1024 + 1))
                self.ring("DONE 7 tasks/7.md")
                result = self.turn()
                self.assertEqual((result["task"], result["action"]), ("7", "receipt-refused"))
                state = json.loads((self.root / "lead-state.json").read_text())
                self.assertEqual(state["tasks"]["7"]["status"], "review-refused")
                self.assertEqual(self.turn()["task"], "8")

    def test_required_task_behind_a_stopped_dependency_escalates_once_then_fails(self):
        self.init([self.task("7", required=False), self.task("8", after=["7"])])
        self.turn()
        self.ring("STOPPED 7 optional input unavailable")
        self.assertEqual(self.turn()["action"], "stop")
        held = self.turn()
        self.assertEqual(held["action"], "escalate")
        question = (self.root / f"escalations/{held['escalation']}.md").read_text()
        self.assertIn("Task 8 depends on 7", question)
        self.assertIn("cannot accept a stopped dependency", question)
        self.assertEqual(self.turn()["action"], "wait-human")
        self.command("answer", {"record_root": str(self.root), "escalation": held["escalation"],
                                "by": "human", "decision": "continue", "answer": "Proceed."})
        self.assertEqual(self.turn()["action"], "human-answer")
        failed = self.turn()
        self.assertEqual(failed["action"], "mission-failed")
        self.assertIn("Task 8 waits on 7 (stopped)", failed["reason"])
        self.assertIn("Task 8 waits on 7 (stopped)", (self.root / "mission-failed.md").read_text())
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["outcome"]["status"], "failed")
        self.assertEqual(len(state["escalations"]), 1)
        self.assertEqual(len(self.sent_states), 1)

    def test_identical_held_after_continue_escalates_again_but_the_stale_line_does_not(self):
        self.init()
        self.turn()
        self.ring("HELD 7 need a different model")
        held = self.turn()
        self.assertEqual(held["action"], "escalate")
        self.command("answer", {"record_root": str(self.root), "escalation": held["escalation"],
                                "by": "human", "decision": "continue", "answer": "Keep the roster."})
        self.assertEqual(self.turn()["action"], "human-answer")
        self.assertEqual(self.turn()["action"], "wait")
        self.screens["scratch:p1"] = "HELD 7 need a different model\n" + self.screens["scratch:p1"]
        self.snapshot["agents"][0]["state_change_seq"] += 1
        again = self.turn()
        self.assertEqual(again["action"], "escalate")
        self.assertNotEqual(again["escalation"], held["escalation"])

    def continue_ring(self, line, forget_counts=False):
        self.init()
        self.turn()
        self.ring(line)
        first = self.turn()
        self.assertEqual(first["action"], "escalate")
        if forget_counts:  # a record written before visible counts were kept
            path = self.root / "lead-state.json"
            state = json.loads(path.read_text())
            state.pop("ring_counts", None)
            path.write_text(json.dumps(state))
        self.command("answer", {"record_root": str(self.root), "escalation": first["escalation"],
                                "by": "human", "decision": "continue", "answer": "Carry on."})
        self.assertEqual(self.turn()["action"], "human-answer")
        return first

    def ring_again(self, line):
        self.screens["scratch:p1"] = line + "\n" + self.screens["scratch:p1"]
        self.snapshot["agents"][0]["state_change_seq"] += 1

    def assert_repeat_right_after_the_answer_escalates(self, line):
        first = self.continue_ring(line)
        self.ring_again(line)
        again = self.turn()
        self.assertEqual(again["action"], "escalate")
        self.assertNotEqual(again["escalation"], first["escalation"])

    def test_identical_held_right_after_the_answer_escalates_without_an_intervening_wait(self):
        self.assert_repeat_right_after_the_answer_escalates("HELD 7 need a different model")

    def test_identical_help_right_after_the_answer_escalates_without_an_intervening_wait(self):
        self.assert_repeat_right_after_the_answer_escalates("HELP 7 a question the plan does not answer")

    def test_the_answered_ring_left_on_screen_stays_suppressed(self):
        self.continue_ring("HELD 7 need a different model")
        self.assertEqual([self.turn()["action"] for _ in range(2)], ["wait", "wait"])
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(len(state["escalations"]), 1)

    def test_a_record_without_visible_counts_takes_them_from_the_answer_turn_observation(self):
        first = self.continue_ring("HELD 7 need a different model", forget_counts=True)
        self.ring_again("HELD 7 need a different model")
        again = self.turn()
        self.assertEqual(again["action"], "escalate")
        self.assertNotEqual(again["escalation"], first["escalation"])

    def answered_under_older_code(self, line):
        """Seed the state an older lead saved after the answer: released text at an unknown count."""
        first = self.continue_ring(line)
        path = self.root / "lead-state.json"
        state = json.loads(path.read_text())
        state.pop("ring_counts", None)
        state["tasks"]["7"]["stale_rings"] = {line: None}
        path.write_text(json.dumps(state))
        return first

    def assert_next_continue_suppresses(self, escalation):
        self.command("answer", {"record_root": str(self.root), "escalation": escalation,
                                "by": "human", "decision": "continue", "answer": "Carry on."})
        self.assertEqual(self.turn()["action"], "human-answer")
        self.assertEqual(self.turn()["action"], "wait")

    def test_an_answered_older_record_does_not_swallow_a_repeat_behind_an_unknown_count(self):
        first = self.answered_under_older_code("HELD 7 need a different model")
        self.ring_again("HELD 7 need a different model")
        again = self.turn()
        self.assertEqual(again["action"], "escalate")
        self.assertNotEqual(again["escalation"], first["escalation"])
        self.assert_next_continue_suppresses(again["escalation"])

    def test_an_unknown_count_releases_the_old_copy_once_then_suppresses_normally(self):
        first = self.answered_under_older_code("HELP 7 a question the plan does not answer")
        again = self.turn()
        self.assertEqual(again["action"], "escalate")
        self.assertNotEqual(again["escalation"], first["escalation"])
        self.assert_next_continue_suppresses(again["escalation"])

    def partial_return(self, text="\n## Return\nCloses: 7\n"):
        with (self.root / "tasks/7.md").open("a") as stream:
            stream.write(text)

    def test_pending_review_with_an_idle_unchanged_owner_escalates_on_the_third_observation(self):
        self.init()
        self.turn()
        self.partial_return()
        self.assertEqual(self.turn()["action"], "receipt-pending")
        self.assertEqual(self.turn()["action"], "wait")
        stalled = self.turn()
        self.assertEqual(stalled["action"], "escalate")
        self.assertIn("idle", (self.root / f"escalations/{stalled['escalation']}.md").read_text())
        self.assertEqual(self.turn()["action"], "wait-human")

    def test_pending_review_entered_while_the_owner_works_escalates_on_the_third_idle_observation(self):
        self.init()
        self.turn()
        self.snapshot["agents"][0]["agent_status"] = "working"
        self.snapshot["agents"][0]["state_change_seq"] += 1
        self.partial_return()
        self.assertEqual(self.turn()["action"], "receipt-pending")
        self.snapshot["agents"][0]["agent_status"] = "idle"
        self.snapshot["agents"][0]["state_change_seq"] += 1
        self.assertEqual([self.turn()["action"] for _ in range(3)], ["wait", "wait", "escalate"])

    def test_pending_review_count_resets_on_a_changed_return_or_a_working_owner(self):
        self.init()
        self.turn()
        self.partial_return()
        self.assertEqual(self.turn()["action"], "receipt-pending")
        self.assertEqual(self.turn()["action"], "wait")
        self.partial_return("\nstill writing\n")
        self.assertEqual(self.turn()["action"], "receipt-pending")
        self.assertEqual(self.turn()["action"], "wait")
        self.snapshot["agents"][0]["agent_status"] = "working"
        self.snapshot["agents"][0]["state_change_seq"] += 1
        self.assertEqual(self.turn()["action"], "wait")
        self.snapshot["agents"][0]["agent_status"] = "idle"
        self.snapshot["agents"][0]["state_change_seq"] += 1
        self.assertEqual([self.turn()["action"] for _ in range(3)], ["wait", "wait", "escalate"])

    def test_init_takes_the_record_lock_before_checking_emptiness(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        self.root.mkdir()
        with lead.record_lock(self.root.resolve()):
            params = {"record_root": str(self.root), "project_root": str(self.project),
                      "workspace_id": "scratch", "lead_pane_id": "scratch:lead", "mission": "m",
                      "members": [{"name": "alpha", "pane_id": "scratch:p1", "input_box": {
                          "agent": "fake", "start": "[INPUT]", "end": "[/INPUT]"}}],
                      "tasks": [self.task()]}
            self.assertEqual(self.command("init", params, expected=1)["error"]["code"], "lead_in_progress")
        self.assertEqual(self.init()["result"]["action"], "initialized")

    def test_unmapped_help_joins_the_held_escalation_batch(self):
        self.add_member("beta", "scratch:p2")
        self.init([self.task("7"), self.task("8", "beta")])
        self.turn()
        self.turn()
        self.ring("HELD 7 need a different model")
        self.ring("HELP 8 which database", pane="scratch:p2")
        held = self.turn()
        self.assertEqual(held["action"], "escalate")
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["escalations"][0]["tasks"], ["7", "8"])
        self.assertIn("which database", (self.root / "escalations/1.md").read_text())

    def test_failed_human_answer_write_leaves_the_escalation_waiting(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        self.init()
        self.turn()
        self.ring("HELD 7 need a different model")
        held = self.turn()
        self.command("answer", {"record_root": str(self.root), "escalation": held["escalation"],
                                "by": "human", "decision": "continue", "answer": "Keep the roster."})
        (self.root / "answers").write_text("not a directory\n")
        state = json.loads((self.root / "lead-state.json").read_text())
        with self.assertRaises(OSError):
            lead.human_turn(self.root.resolve(), state, state["escalations"][0])
        self.assertEqual(state["escalations"][0]["status"], "waiting")
        self.assertEqual(state["tasks"]["7"]["status"], "held")

    def test_non_utf8_accepted_return_refuses_completion_not_the_turn(self):
        self.init()
        self.turn()
        self.receipt()
        self.assertEqual(self.turn()["action"], "accept")
        with (self.root / "tasks/7.md").open("ab") as stream:
            stream.write(b"\xff\n")
        self.assertEqual(self.turn()["action"], "completion-refused")

    def test_required_stop_fails_the_mission_before_queued_optional_work_is_sent(self):
        # External review A2: optional work was dispatched, then escalated, while a required failure waited.
        self.init([self.task(value=30), self.task("8", "alpha", required=False)])
        self.assertEqual(self.turn()["action"], "dispatch")
        self.ring("STOPPED 7 auth is unreachable")
        self.assertEqual(self.turn()["action"], "stop")
        self.assertEqual(self.turn()["action"], "mission-failed")
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["tasks"]["8"]["status"], "queued")
        self.assertEqual(len(self.sent_states), 1)
        refused = self.command("lead", {"record_root": str(self.root)}, expected=1)
        self.assertEqual(refused["error"]["code"], "mission_failed")

    def test_a_waiting_human_answer_is_handled_before_a_required_failure(self):
        self.add_member("beta", "scratch:p2")
        self.init([self.task(value=30), self.task("8", "beta", value=20)])
        self.turn()
        self.turn()
        self.ring("HELD 8 need a different model", pane="scratch:p2")
        held = self.turn()
        self.assertEqual(held["action"], "escalate")
        self.ring("STOPPED 7 auth is unreachable")
        self.assertEqual(self.turn()["action"], "wait-human")
        self.command("answer", {"record_root": str(self.root), "escalation": held["escalation"],
                                "by": "human", "decision": "continue", "answer": "Carry on."})
        self.assertEqual(self.turn()["action"], "human-answer")
        self.assertEqual(self.turn()["action"], "stop")
        self.assertEqual(self.turn()["action"], "mission-failed")

    def test_a_non_object_lead_state_is_a_structured_refusal(self):
        # External review A4: both lead entry points dereferenced the parsed index without a shape check.
        self.init()
        (self.root / "lead-state.json").write_text("[]")
        before = len(self.peer.requests)
        refused = self.command("lead", {"record_root": str(self.root)}, expected=1)
        self.assertEqual(refused["error"]["code"], "record_corrupt")
        self.assertIn("restore", refused["error"]["message"])
        answer = self.command("answer", {"record_root": str(self.root), "escalation": "1", "by": "human",
                                         "decision": "continue", "answer": "x"}, expected=1)
        self.assertEqual(answer["error"]["code"], "record_corrupt")
        self.assertEqual(len(self.peer.requests), before)

    def test_unreachable_optional_work_is_stopped_as_not_run_and_the_mission_closes(self):
        self.init([self.task("7", required=False), self.task("8", required=False, after=["7"]),
                   self.task("10", required=False, after=["8"]), self.task("9")])
        self.turn()
        self.ring("STOPPED 7 optional input unavailable")
        self.assertEqual(self.turn()["action"], "stop")
        self.assertEqual(self.turn()["task"], "9")
        self.receipt("9")
        self.ring("DONE 9 tasks/9.md")
        actions = [self.turn()["action"] for _ in range(3)]
        self.assertEqual(actions[-1], "complete", actions)
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual({t: state["tasks"][t]["status"] for t in ("8", "10")}, {"8": "stopped", "10": "stopped"})
        checks = json.loads((self.root / "closing-checks.json").read_text())
        not_run = {c["task"]: c["not_run"] for c in checks if "not_run" in c}
        self.assertEqual(not_run, {"8": "dependency 7 ended stopped without acceptance",
                                   "10": "dependency 8 ended stopped without acceptance"})
        self.assertEqual(len(self.sent_states), 2)

    def test_required_task_behind_unreachable_optional_chain_still_escalates(self):
        self.init([self.task("7", required=False), self.task("8", required=False, after=["7"]),
                   self.task("9", after=["8"])])
        self.turn()
        self.ring("STOPPED 7 optional input unavailable")
        self.assertEqual(self.turn()["action"], "stop")
        held = self.turn()
        self.assertEqual((held["action"], held["task"]), ("escalate", "9"))
        self.assertIn("Task 9 depends on 8, which ended stopped", (self.root / "escalations/1.md").read_text())

    def test_stalled_review_continued_by_a_human_is_monitored_again(self):
        self.init()
        self.turn()
        self.partial_return()
        self.assertEqual([self.turn()["action"] for _ in range(3)], ["receipt-pending", "wait", "escalate"])
        self.command("answer", {"record_root": str(self.root), "escalation": "1", "by": "human",
                                "decision": "continue", "answer": "Finish the return."})
        self.assertEqual(self.turn()["action"], "human-answer")
        again = [self.turn() for _ in range(3)]
        self.assertEqual([r["action"] for r in again], ["wait", "wait", "escalate"])
        self.assertEqual(again[-1]["escalation"], "2")

    def snapshots_fail_after(self, allowed):
        reply, left = self.peer.reply, [allowed]

        def limited(request):
            if request["method"] == "session.snapshot":
                left[0] -= 1
                if left[0] < 0:
                    return (json.dumps({"id": request["id"], "error": {
                        "code": "unavailable", "message": "fixture snapshot outage"}}) + "\n").encode()
            return reply(request)
        self.peer.reply = limited

    def test_failed_trailing_watch_returns_the_recorded_turn_with_a_wait_diagnostic(self):
        self.init()
        self.turn()
        self.snapshots_fail_after(1)
        result = self.turn()
        self.assertEqual(result["action"], "wait")
        self.assertTrue(result["wait"]["error"].startswith("observation_unavailable: "), result["wait"])
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["turn"], result["turn"])

    def test_unavailable_first_observation_still_refuses_the_turn(self):
        self.init()
        self.turn()
        before = (self.root / "lead-state.json").read_bytes()
        self.snapshots_fail_after(0)
        self.command("lead", {"record_root": str(self.root), "wait_seconds": 0.03}, expected=1)
        self.assertEqual((self.root / "lead-state.json").read_bytes(), before)

    def verifier_task(self, task_id="7", timeout=5, **changes):
        return self.task(task_id, claims={"suite": {"check": [sys.executable, "-c", self.VERIFIER],
                                                    "timeout_seconds": timeout}},
                         files_changed=[], **changes)

    def verifier_receipt(self, active="7", status="passed", note="worker ran the suite"):
        path = self.root / f"tasks/{active}.md"
        with path.open("a") as stream:
            stream.write(f"\n## Return — attempt {active}\n\nCloses: {active}\n\n"
                         f"### Result\nDone.\n\n### Claims\n- suite: {status} ({note})\n\n"
                         f"### Evidence\n{note}\n")
        return path

    def verifier_runs(self):
        runs = self.project / "verifier-runs"
        return runs.read_text().splitlines() if runs.exists() else []

    def file_checker(self, relative=False, launcher=False):
        """A plan whose check is a checker script named by path, over a product that lacks the required behaviour."""
        checker = self.project / ("check_behavior.sh" if launcher else "check_behavior.py")
        if launcher:
            checker.write_text("#!/bin/sh\ntest \"$(cat product.txt)\" = hello\n")
            checker.chmod(0o755)
            argv = [str(checker)]
        else:
            checker.write_text("from pathlib import Path\nimport sys\n"
                               "sys.exit(0 if Path('product.txt').read_text() == 'hello\\n' else 3)\n")
            argv = [sys.executable, checker.name if relative else str(checker)]
        (self.project / "product.txt").write_text("missing required behavior\n")
        self.init([self.task("7", claims={"suite": {"check": argv, "timeout_seconds": 5}}, files_changed=[])])
        self.turn()
        self.verifier_receipt()
        return checker

    def assert_held_as_unverified(self, result, needle):
        self.assertEqual(result["action"], "escalate", result)
        state = self.lead_state()
        self.assertEqual(state["tasks"]["7"]["status"], "held")
        self.assertIn(needle, (self.root / result["evidence"]).read_text())
        self.assertFalse((self.root / "reviews").exists(), "a held task was never accepted")

    def test_an_unchanged_checker_file_still_rejects_missing_behaviour(self):
        self.file_checker()
        result = self.turn()
        self.assertEqual(result["action"], "correct", result)
        self.assertIn("trusted verifier exited 3", result["reason"])

    def test_a_changed_checker_file_is_held_never_accepted(self):
        checker = self.file_checker()
        before = (self.root / "lead-state.json").read_bytes()
        checker.write_text("import sys\nsys.exit(0)\n")  # the checker now passes missing behaviour
        self.assertEqual((self.root / "lead-state.json").read_bytes(), before, "the plan itself did not change")
        self.assert_held_as_unverified(self.turn(), "changed since admission")
        self.assertEqual((self.project / "product.txt").read_text(), "missing required behavior\n")

    def test_a_deleted_checker_file_is_held(self):
        checker = self.file_checker()
        checker.unlink()
        self.assert_held_as_unverified(self.turn(), "missing since admission")

    def test_a_checker_named_relative_to_the_pinned_cwd_is_pinned(self):
        checker = self.file_checker(relative=True)
        checker.write_text("import sys\nsys.exit(0)\n")
        self.assert_held_as_unverified(self.turn(), "changed since admission")

    def test_a_launcher_named_as_argv0_is_pinned(self):
        checker = self.file_checker(launcher=True)
        checker.write_text("#!/bin/sh\ntrue\n")
        self.assert_held_as_unverified(self.turn(), "changed since admission")

    def test_a_record_with_no_identity_pins_is_held_not_run(self):
        self.file_checker()
        state = self.lead_state()
        del state["tasks"]["7"]["claims"]["suite"]["pins"]
        (self.root / "lead-state.json").write_text(json.dumps(state))
        self.assert_held_as_unverified(self.turn(), "no identity pins")

    def test_pins_cover_regular_files_only_and_resolve_argv0_through_path(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        bin_dir = self.project / "bin"
        bin_dir.mkdir()
        tool = bin_dir / "mycheck"
        tool.write_text("#!/bin/sh\nexit 0\n")
        tool.chmod(0o755)
        (self.project / "data").mkdir()
        (self.project / "notes.txt").write_text("n")
        with unittest.mock.patch.dict(os.environ, {"PATH": f"{bin_dir}:/usr/bin:/bin"}):
            pins = lead.verifier_pins(["mycheck", "-m", "json.tool", "data", "notes.txt", "ghost.py", "--flag=x"],
                                      str(self.project))
        self.assertEqual(pins["head"], {"path": str(tool), "sha256": hashlib.sha256(tool.read_bytes()).hexdigest()})
        self.assertEqual([f["path"] for f in pins["files"]], [str(self.project / "notes.txt")],
                         "a directory, a module name, a missing file and a flag are not pinned")
        with self.assertRaises(lead.Refusal) as caught:
            lead.verifier_pins([str(self.project / "ghost")], str(self.project))
        self.assertEqual(caught.exception.code, "schema_invalid", "an argv0 that does not resolve is refused")

    def in_caller(self, caller, path):
        """Run the lead from `caller` with `path` as PATH, as a lead started somewhere other than the project would be."""
        stack = contextlib.ExitStack()
        stack.callback(os.chdir, os.getcwd())
        os.chdir(caller)
        stack.enter_context(unittest.mock.patch.dict(os.environ, {"PATH": path}))
        return stack

    def path_checker(self, relative, caller_has_tool=True):
        """A checker found through PATH. The project's bin/pathcheck is the real one; caller/bin/pathcheck is a decoy that always fails."""
        caller, project_bin = self.project / "caller", self.project / "bin"
        (caller / "bin").mkdir(parents=True)
        project_bin.mkdir()
        tool = project_bin / "pathcheck"
        tool.write_text('#!/bin/sh\nprintf project-tool >> ran-marker\ntest "$(cat product.txt)" = hello\n')
        tool.chmod(0o755)
        if caller_has_tool:
            decoy = caller / "bin" / "pathcheck"
            decoy.write_text("#!/bin/sh\nprintf caller-tool >> ran-marker\nexit 3\n")
            decoy.chmod(0o755)
        (self.project / "product.txt").write_text("missing required behavior\n")
        return caller, tool, ("bin" if relative else str(project_bin)) + ":/usr/bin:/bin"

    def admit_path_checker(self, caller, path):
        with self.in_caller(caller, path):
            self.init([self.task(claims={"suite": {"check": ["pathcheck"], "timeout_seconds": 5}}, files_changed=[])])
            self.turn()
            self.verifier_receipt()
        return self.lead_state()["tasks"]["7"]["claims"]["suite"]["pins"]

    def ran(self):
        marker = self.project / "ran-marker"
        return marker.read_text() if marker.exists() else None

    def test_a_relative_path_entry_is_resolved_in_the_pinned_cwd_not_the_callers(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        caller, tool, _ = self.path_checker(relative=True)
        cwd = str(self.project)
        with self.in_caller(caller, "bin:/usr/bin:/bin"):
            for argv0 in ("pathcheck", "bin/pathcheck", "./bin/pathcheck"):
                self.assertEqual(lead.resolve_head(argv0, cwd), str(tool), argv0)
        root_tool = self.project / "rootcheck"
        root_tool.write_text("#!/bin/sh\n")
        root_tool.chmod(0o755)
        with self.in_caller(caller, ":/usr/bin"):
            self.assertEqual(lead.resolve_head("rootcheck", cwd), str(root_tool), "an empty PATH entry is the pinned cwd")

    def symlink_dotdot_checkers(self):
        """project/link -> real/sub, so `link/..` is `real`. real/checker is the intended checker and fails (the product is
        wrong); project/checker is a decoy that passes. A path that lets `..` cancel `link` lexically names the decoy."""
        real = self.project / "real"
        (real / "sub").mkdir(parents=True)
        (self.project / "link").symlink_to(real / "sub", target_is_directory=True)
        intended = real / "checker"
        intended.write_text('#!/bin/sh\nprintf intended >> ran-marker\ntest "$(cat product.txt)" = hello\n')
        intended.chmod(0o755)
        decoy = self.project / "checker"
        decoy.write_text("#!/bin/sh\nprintf decoy >> ran-marker\nexit 0\n")
        decoy.chmod(0o755)
        (self.project / "product.txt").write_text("missing required behavior\n")
        return intended

    def test_a_symlink_followed_by_dotdot_resolves_as_the_kernel_does(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        intended = self.symlink_dotdot_checkers()
        cwd = str(self.project)
        named = {"./link/../checker": "link/../checker", "link/../checker": "link/../checker", "checker": "link/../checker",
                 "./real/sub/../checker": "real/sub/../checker"}
        with self.in_caller(self.project, "link/..:/usr/bin:/bin"):
            for argv0, form in named.items():
                head = lead.resolve_head(argv0, cwd)
                self.assertEqual(head, os.path.join(cwd, form), argv0)
                self.assertEqual(os.path.realpath(head), str(intended.resolve()), argv0)
        with self.in_caller(self.project, "/usr/bin:/bin"):
            head = lead.resolve_head("./link/../checker", cwd)
            self.assertEqual(head, os.path.join(cwd, "link/../checker"))
            self.assertEqual(os.path.realpath(head), str(intended.resolve()))

    def assert_dotdot_checker_runs_as_named(self, argv0, path):
        intended = self.symlink_dotdot_checkers()
        with self.in_caller(self.project, path):
            self.init([self.task(claims={"suite": {"check": [argv0], "timeout_seconds": 5}}, files_changed=[])])
            self.turn()
            self.verifier_receipt()
            pins = self.lead_state()["tasks"]["7"]["claims"]["suite"]["pins"]
            result = self.turn()
        self.assertEqual(pins["head"]["path"], os.path.join(str(self.project.resolve()), "link/../checker"))
        self.assertEqual(os.path.realpath(pins["head"]["path"]), str(intended.resolve()))
        self.assertEqual(result["action"], "correct", result)
        self.assertEqual(self.ran(), "intended", "the file that was pinned is the file that ran")

    def test_a_slash_path_through_a_symlink_and_dotdot_runs_the_checker_it_names_not_the_decoy(self):
        self.assert_dotdot_checker_runs_as_named("./link/../checker", "/usr/bin:/bin")

    def test_a_path_entry_through_a_symlink_and_dotdot_runs_the_checker_it_names_not_the_decoy(self):
        self.assert_dotdot_checker_runs_as_named("checker", "link/..:/usr/bin:/bin")

    def test_a_symlinked_final_executable_keeps_its_own_path(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        target = self.project / "real" / "tool-target"
        target.parent.mkdir()
        target.write_text("#!/bin/sh\nexit 0\n")
        target.chmod(0o755)
        (self.project / "bin").mkdir()
        (self.project / "bin" / "tool").symlink_to(target)
        (self.project / "dirlink").symlink_to(self.project / "bin", target_is_directory=True)
        stored = os.path.join(str(self.project), "bin", "tool")
        expected = {"./bin/tool": stored, "tool": stored,
                    "./dirlink/tool": os.path.join(str(self.project), "dirlink", "tool"),
                    "./dirlink/../bin/tool": os.path.join(str(self.project), "dirlink", "..", "bin", "tool")}
        with self.in_caller(self.project, "bin:/usr/bin:/bin"):
            for argv0, want in expected.items():
                head = lead.resolve_head(argv0, str(self.project))
                self.assertEqual(head, want, argv0)
                self.assertTrue(os.path.islink(head), "the stored head is the link, not the file it points at")
                self.assertNotEqual(head, str(target.resolve()))

    def test_a_venv_python_symlink_launches_as_the_venv(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        base = Path(os.path.realpath(sys.executable))
        venv = self.project / "venv"
        (venv / "bin").mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text(f"home = {base.parent}\ninclude-system-site-packages = false\n"
                                         f"version = {sys.version.split()[0]}\n")
        (venv / "bin" / "python").symlink_to(base)
        head = lead.resolve_head("./venv/bin/python", str(self.project))
        self.assertEqual(head, str(venv / "bin" / "python"))
        prefix = "import os, sys; print(os.path.realpath(sys.prefix))"
        launched = subprocess.run([head, "-I", "-c", prefix], capture_output=True, text=True, timeout=30)
        self.assertEqual(launched.stdout.strip(), os.path.realpath(venv), launched.stderr)
        resolved = subprocess.run([str(base), "-I", "-c", prefix], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(resolved.stdout.strip(), os.path.realpath(venv), "launching the target would drop the venv")

    def test_a_symlinked_directory_with_no_dotdot_is_stored_unresolved(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        (self.project / "real").mkdir()
        checker = self.project / "real" / "checker"
        checker.write_text("#!/bin/sh\nexit 0\n")
        checker.chmod(0o755)
        (self.project / "link").symlink_to(self.project / "real", target_is_directory=True)
        cwd = str(self.project)
        expected = os.path.join(cwd, "link", "checker")
        with self.in_caller(self.project, "link:/usr/bin:/bin"):
            for argv0 in ("./link/checker", "link/checker", "checker"):
                head = lead.resolve_head(argv0, cwd)
                self.assertEqual(head, expected, argv0)
                self.assertTrue(os.path.islink(os.path.dirname(head)), "the symlinked directory is still in the stored path")
                self.assertNotEqual(head, os.path.realpath(checker))

    def test_what_follows_the_last_dotdot_is_kept_as_found(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        (self.project / "real" / "sub").mkdir(parents=True)
        (self.project / "real" / "bin").mkdir()
        checker = self.project / "real" / "bin" / "checker"
        checker.write_text("#!/bin/sh\nexit 0\n")
        checker.chmod(0o755)
        (self.project / "link").symlink_to(self.project / "real" / "sub", target_is_directory=True)
        (self.project / "real" / "dl").symlink_to(self.project / "real" / "bin", target_is_directory=True)
        cwd = str(self.project)
        named = {"./link/../dl/checker": "link/../dl/checker", "./link/../dl/../dl/checker": "link/../dl/../dl/checker",
                 "link/../dl/./checker": "link/../dl/checker"}
        for argv0, form in named.items():
            head = lead.resolve_head(argv0, cwd)
            self.assertEqual(head, os.path.join(cwd, form), argv0)
            self.assertEqual(os.path.realpath(head), os.path.realpath(checker), argv0)
            self.assertIn("dl", head.split(os.sep), "the symlinked directory after the last `..` is still in the stored path")

    def test_the_last_dotdot_decides_not_the_first(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        (self.project / "a").mkdir()
        (self.project / "real" / "sub").mkdir(parents=True)
        for where in (self.project, self.project / "real"):
            (where / "checker").write_text("#!/bin/sh\nexit 0\n")
            (where / "checker").chmod(0o755)
        (self.project / "link").symlink_to(self.project / "real" / "sub", target_is_directory=True)
        head = lead.resolve_head("./a/../link/../checker", str(self.project))
        self.assertEqual(head, os.path.join(str(self.project), "a/../link/../checker"))
        self.assertEqual(os.path.realpath(head), os.path.realpath(self.project / "real" / "checker"),
                         "the first `..` cancels `a` and the second is the parent of link's target, not of link: the kernel's file")
        self.assertNotEqual(os.path.realpath(head), os.path.realpath(self.project / "checker"), "not the decoy")

    def test_a_venv_bin_symlink_reached_through_dotdot_keeps_the_venv(self):
        """Like python, the launcher finds pyvenv.cfg from the path it was started by, with `x/..` pairs collapsed lexically.
        venv/bin -> ../shared/bin, reached as ./venv/bin/../bin/launcher."""
        sys.path.insert(0, str(CLI.parent))
        import lead
        (self.project / "shared" / "bin").mkdir(parents=True)
        launcher = self.project / "shared" / "bin" / "launcher"
        launcher.write_text('#!/bin/sh\np=$0\nwhile :; do\n  q=$(printf %s "$p" | sed \'s#/[^/][^/]*/\\.\\./#/#\')\n'
                            '  [ "$q" = "$p" ] && break\n  p=$q\ndone\nd=${p%/*}\nd=${d%/*}\n'
                            'if [ -f "$d/pyvenv.cfg" ]; then echo venv; else echo base; fi\n')
        launcher.chmod(0o755)
        (self.project / "venv").mkdir()
        (self.project / "venv" / "pyvenv.cfg").write_text("home = /nowhere\n")
        (self.project / "venv" / "bin").symlink_to("../shared/bin", target_is_directory=True)
        cwd = str(self.project)
        for argv0 in ("./venv/bin/launcher", "./venv/bin/../bin/launcher", "./venv/bin/../bin/../bin/launcher"):
            direct = subprocess.run([argv0], cwd=cwd, capture_output=True, text=True, timeout=10).stdout.strip()
            self.assertEqual(direct, "venv", f"control: {argv0} started by hand")
            head = lead.resolve_head(argv0, cwd)
            self.assertEqual(head, os.path.join(cwd, argv0[2:]), argv0)
            self.assertEqual(subprocess.run([head], capture_output=True, text=True, timeout=10).stdout.strip(), direct, argv0)

    def test_a_real_venv_whose_bin_is_a_symlink_keeps_the_venv_through_dotdot(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        interpreter = self.non_framework_python()
        if interpreter is None:
            self.skipTest("no non-framework python with the venv module was found")
        venv = self.project / "venv"
        made = subprocess.run([interpreter, "-I", "-m", "venv", "--without-pip", str(venv)], capture_output=True, text=True, timeout=120)
        self.assertEqual(made.returncode, 0, made.stderr)
        (self.project / "shared").mkdir()
        (venv / "bin").rename(self.project / "shared" / "bin")
        (venv / "bin").symlink_to("../shared/bin", target_is_directory=True)
        (self.project / "proj" / "sub").mkdir(parents=True)
        prefix = "import os, sys; print(os.path.realpath(sys.prefix))"
        for argv0, where in (("./venv/bin/python", ""), ("./venv/bin/../bin/python", ""), ("./venv/bin/../bin/../bin/python", ""),
                             ("../venv/bin/python", "proj"), ("../../venv/bin/../bin/python", "proj/sub")):
            cwd = str(self.project / where) if where else str(self.project)
            direct = subprocess.run([argv0, "-I", "-c", prefix], cwd=cwd, capture_output=True, text=True, timeout=30)
            self.assertEqual(direct.stdout.strip(), os.path.realpath(venv), f"control: {argv0} started by hand: {direct.stderr}")
            head = lead.resolve_head(argv0, cwd)
            launched = subprocess.run([head, "-I", "-c", prefix], capture_output=True, text=True, timeout=30)
            self.assertEqual(launched.stdout.strip(), direct.stdout.strip(), f"{argv0} -> {head}: {launched.stderr}")

    def test_the_stored_head_keeps_dotdot_verbatim_and_drops_dot_and_repeated_slashes(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        (self.project / "real" / "sub").mkdir(parents=True)
        intended = self.project / "real" / "checker"
        for where in (self.project, self.project / "real"):
            (where / "checker").write_text("#!/bin/sh\nexit 0\n")
            (where / "checker").chmod(0o755)
        (self.project / "link").symlink_to(self.project / "real" / "sub", target_is_directory=True)
        cwd = str(self.project)
        named = os.path.join(cwd, "link", "..", "checker")
        for argv0 in ("./link/../checker", "link/../checker", ".//link//..//checker", "./link/./../checker", "link/.././/./checker"):
            head = lead.resolve_head(argv0, cwd)
            self.assertEqual(head, named, argv0)
            self.assertTrue(os.path.samefile(head, intended), "the kernel resolves the stored path to the checker the name means")
        self.assertEqual(lead.resolve_head("./link/../checker", cwd + "/./"), named, "dots and repeated slashes in cwd are dropped too")
        self.assertEqual(lead.resolve_head(os.path.join(cwd, ".", "link", "..", "checker"), cwd), named, "an absolute name too")
        with self.in_caller(self.project, "link/..:/usr/bin:/bin"):
            self.assertEqual(lead.resolve_head("checker", cwd), named, "a PATH entry named link/..")
            self.assertTrue(os.path.samefile(lead.resolve_head("checker", cwd), intended))

    def test_a_symlinked_venv_bin_directory_keeps_the_venv(self):
        """A launcher that, like python, finds pyvenv.cfg from the path it was started by: venv/bin -> ../shared/bin."""
        sys.path.insert(0, str(CLI.parent))
        import lead
        (self.project / "shared" / "bin").mkdir(parents=True)
        launcher = self.project / "shared" / "bin" / "launcher"
        launcher.write_text('#!/bin/sh\nd=${0%/*}\nd=${d%/*}\nif [ -f "$d/pyvenv.cfg" ]; then echo venv; else echo base; fi\n')
        launcher.chmod(0o755)
        (self.project / "venv").mkdir()
        (self.project / "venv" / "pyvenv.cfg").write_text("home = /nowhere\n")
        (self.project / "venv" / "bin").symlink_to("../shared/bin", target_is_directory=True)

        def launched(path):
            return subprocess.run([path], capture_output=True, text=True, timeout=10).stdout.strip()

        self.assertEqual(launched(str(self.project / "venv" / "bin" / "launcher")), "venv", "control: started by its venv path")
        self.assertEqual(launched(str(launcher)), "base", "control: started by the shared path it points at")
        head = lead.resolve_head("./venv/bin/launcher", str(self.project))
        self.assertEqual(head, os.path.join(str(self.project), "venv", "bin", "launcher"))
        self.assertEqual(launched(head), "venv")

    def non_framework_python(self):
        """An interpreter that is not a macOS framework build and can make a venv, or None; a framework python launched
        through a symlinked bin directory behaves the same whether or not the path was resolved."""
        names = [sys.executable] + [shutil.which(n) for n in ("python3", "python3.14", "python3.13", "python3.12", "python3.11")]
        home = pwd.getpwuid(os.getuid()).pw_dir
        names += sorted(glob.glob(os.path.join(home, ".local/share/mise/installs/python/*/bin/python3")), reverse=True)
        probe = "import sysconfig, venv; print(sysconfig.get_config_var('PYTHONFRAMEWORK') or '-')"
        for name in [n for n in names if n]:
            try:
                done = subprocess.run([name, "-I", "-c", probe], capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.SubprocessError):
                continue
            if done.returncode == 0 and done.stdout.strip() == "-":
                return name
        return None

    def test_a_real_venv_whose_bin_is_a_symlink_keeps_the_venv(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        interpreter = self.non_framework_python()
        if interpreter is None:
            self.skipTest("no non-framework python with the venv module was found")
        venv = self.project / "venv"
        made = subprocess.run([interpreter, "-I", "-m", "venv", "--without-pip", str(venv)], capture_output=True, text=True, timeout=120)
        self.assertEqual(made.returncode, 0, made.stderr)
        (self.project / "shared").mkdir()
        (venv / "bin").rename(self.project / "shared" / "bin")
        (venv / "bin").symlink_to("../shared/bin", target_is_directory=True)
        prefix = "import os, sys; print(os.path.realpath(sys.prefix))"
        direct = subprocess.run([str(venv / "bin" / "python"), "-I", "-c", prefix], capture_output=True, text=True, timeout=30)
        self.assertEqual(direct.stdout.strip(), os.path.realpath(venv), direct.stderr)
        head = lead.resolve_head("./venv/bin/python", str(self.project))
        launched = subprocess.run([head, "-I", "-c", prefix], capture_output=True, text=True, timeout=30)
        self.assertEqual(launched.stdout.strip(), os.path.realpath(venv), launched.stderr)

    def test_a_relative_path_checker_still_rejects_missing_behaviour_and_runs_the_pinned_tool(self):
        caller, tool, path = self.path_checker(relative=True)
        pins = self.admit_path_checker(caller, path)
        self.assertEqual(pins["head"]["path"], str(self.project.resolve() / "bin/pathcheck"))
        with self.in_caller(caller, path):
            result = self.turn()
        self.assertEqual(result["action"], "correct", result)
        self.assertEqual(self.ran(), "project-tool", "the object that was pinned is the object that ran")

    def test_a_relative_path_checker_changed_after_admission_is_held_when_the_caller_has_a_decoy(self):
        caller, tool, path = self.path_checker(relative=True)
        self.admit_path_checker(caller, path)
        tool.write_text("#!/bin/sh\nprintf project-tool >> ran-marker\nexit 0\n")
        with self.in_caller(caller, path):
            self.assert_held_as_unverified(self.turn(), "changed since admission")
        self.assertIsNone(self.ran(), "a held checker is never launched")

    def test_a_relative_path_checker_changed_after_admission_is_held_when_the_caller_has_none(self):
        caller, tool, path = self.path_checker(relative=True, caller_has_tool=False)
        self.admit_path_checker(caller, path)
        tool.write_text("#!/bin/sh\nprintf project-tool >> ran-marker\nexit 0\n")
        with self.in_caller(caller, path):
            self.assert_held_as_unverified(self.turn(), "changed since admission")
        self.assertIsNone(self.ran())

    def test_the_lead_launches_the_pinned_executable_even_if_path_later_resolves_elsewhere(self):
        caller, tool, path = self.path_checker(relative=False)
        self.admit_path_checker(caller, path)
        with self.in_caller(caller, f"{caller / 'bin'}:/usr/bin:/bin"):
            result = self.turn()
        self.assertEqual(result["action"], "correct", result)
        self.assertEqual(self.ran(), "project-tool", "PATH is not consulted again after admission")

    def test_a_verifier_that_does_not_resolve_is_refused_at_admission(self):
        for argv in (["no-such-checker-task43"], [str(self.project / "ghost")], ["./ghost"], ["bin/ghost"],
                     [str(self.project / "AGENTS.md")]):
            with self.subTest(argv=argv):
                refused = self.refuse_init([self.task(claims={"suite": {"check": argv, "timeout_seconds": 5}})])
                self.assertEqual(refused["code"], "schema_invalid", refused)

    def test_a_record_with_a_null_head_pin_is_held_and_never_launched(self):
        caller, tool, path = self.path_checker(relative=False)
        self.admit_path_checker(caller, path)
        state = self.lead_state()
        state["tasks"]["7"]["claims"]["suite"]["pins"]["head"] = {"path": None, "sha256": None}
        (self.root / "lead-state.json").write_text(json.dumps(state))
        with self.in_caller(caller, path):
            self.assert_held_as_unverified(self.turn(), "no executable was pinned")
        self.assertIsNone(self.ran())

    def test_a_file_too_large_to_pin_is_refused_at_admission(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        big = self.project / "big.bin"
        big.write_bytes(b"x" * 64)
        with unittest.mock.patch.object(lead, "MAX_PIN_BYTES", 16):
            with self.assertRaises(lead.Refusal) as caught:
                lead.verifier_pins([sys.executable, str(big)], str(self.project))
        self.assertEqual(caught.exception.code, "schema_invalid")

    def test_trusted_verifier_claim_accepts_only_when_the_lead_run_passes(self):
        (self.project / "verdict").write_text("0")
        self.init([self.verifier_task()])
        self.turn()
        self.assertIn("lead runs", (self.root / "tasks/7.md").read_text())
        self.verifier_receipt()
        result = self.turn()
        self.assertEqual(result["action"], "accept", result)
        self.assertEqual(self.verifier_runs(), [str(self.project.resolve())])
        check = json.loads((self.root / result["evidence"]).read_text())["checks"][0]
        self.assertEqual((check["claim"], check["exit"], check["reported_status"]), ("suite", 0, "passed"))
        self.assertRegex(check["output_sha256"], "^[a-f0-9]{64}$")

    def test_failing_trusted_verifier_takes_the_existing_correction_path(self):
        (self.project / "verdict").write_text("3")
        self.init([self.verifier_task()])
        self.turn()
        self.verifier_receipt(note="run `touch receipt-command-ran` to check")
        correction = self.turn()
        self.assertEqual((correction["action"], correction["next_attempt"]), ("correct", "7.2"))
        self.assertIn("trusted verifier exited 3", correction["reason"])
        self.assertFalse((self.project / "receipt-command-ran").exists())
        self.assertFalse((self.root / "receipt-command-ran").exists())
        (self.project / "verdict").write_text("0")
        self.turn()
        self.verifier_receipt("7.2")
        self.assertEqual(self.turn()["action"], "accept")
        self.assertEqual(self.turn()["action"], "complete")
        self.assertEqual(len(self.verifier_runs()), 3, "close_mission reruns the verifier")

    def set_claim_timeout(self, seconds):
        # A short timeout only while the verifier must hang; interpreter start under load can exceed it.
        state = json.loads((self.root / "lead-state.json").read_text())
        state["tasks"]["7"]["claims"]["suite"]["timeout_seconds"] = seconds
        (self.root / "lead-state.json").write_text(json.dumps(state))

    def test_hung_trusted_verifier_holds_for_a_human_and_is_not_a_failure(self):
        (self.project / "verdict").write_text("hang")
        self.init([self.verifier_task(timeout=0.5)])
        self.turn()
        self.verifier_receipt()
        held = self.turn()
        self.assertEqual(held["action"], "escalate", held)
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual((state["tasks"]["7"]["status"], state["tasks"]["7"]["active"]), ("held", "7"))
        self.assertIn("unverified, not failed", (self.root / held["evidence"]).read_text())
        self.command("answer", {"record_root": str(self.root), "escalation": held["escalation"],
                                "by": "user", "decision": "continue", "answer": "Verifier fixed; recheck."})
        (self.project / "verdict").write_text("0")
        self.set_claim_timeout(30)
        actions = [self.turn()["action"] for _ in range(3)]
        self.assertEqual(actions, ["human-answer", "accept", "complete"])

    def test_known_verifier_failure_survives_a_sibling_that_cannot_verify(self):
        failing = {"check": ["/usr/bin/false"], "timeout_seconds": 60}
        for name, sibling in (("hung", {"check": ["/bin/sleep", "30"], "timeout_seconds": 0.3}),
                              ("unstartable", {"check": [str(self.project / "missing")], "timeout_seconds": 5})):
            for order in ("failure-first", "failure-last"):
                with self.subTest(sibling=name, order=order):
                    self.tearDown()
                    self.setUp()
                    if name == "unstartable":  # resolves at admission, cannot start: a bad interpreter line
                        broken = self.project / "missing"
                        broken.write_text("#!/nonexistent/interpreter\n")
                        broken.chmod(0o755)
                        sibling = {"check": [str(broken)], "timeout_seconds": 5}
                    claims = ({"a": failing, "b": sibling} if order == "failure-first"
                              else {"b": sibling, "a": failing})
                    self.init([self.task(claims=claims, files_changed=[])])
                    self.turn()
                    path = self.root / "tasks/7.md"
                    with path.open("a") as stream:
                        stream.write("\n## Return — attempt 7\n\nCloses: 7\n\n### Result\nDone.\n\n"
                                     "### Claims\n- a: passed (ran)\n- b: passed (ran)\n\n### Evidence\nran\n")
                    result = self.turn()
                    self.assertEqual(result["action"], "correct", result)
                    self.assertIn("a: trusted verifier exited 1", result["reason"])
                    self.assertIn("b:", result["reason"])

    def test_closing_reruns_trusted_verifiers(self):
        (self.project / "verdict").write_text("0")
        self.init([self.verifier_task()])
        self.turn()
        self.verifier_receipt()
        self.assertEqual(self.turn()["action"], "accept")
        (self.project / "verdict").write_text("1")
        self.assertEqual(self.turn()["action"], "completion-refused")
        (self.project / "verdict").write_text("hang")
        self.set_claim_timeout(0.5)
        self.assertEqual(self.turn()["action"], "completion-refused")
        (self.project / "verdict").write_text("0")
        self.set_claim_timeout(30)
        self.assertEqual(self.turn()["action"], "complete")

    def test_malformed_verifier_claims_are_refused_at_init(self):
        for claim in ({"check": "make test", "timeout_seconds": 5},
                      {"check": [], "timeout_seconds": 5},
                      {"check": ["true"]},
                      {"check": ["true"], "timeout_seconds": 601},
                      {"check": ["true"], "timeout_seconds": 0},
                      {"check": ["true"], "timeout_seconds": 5, "path": "x", "sha256": "0" * 64},
                      {"check": ["true"], "timeout_seconds": 5, "cwd": "/"},
                      {"check": ["tr\0ue"], "timeout_seconds": 5}):
            with self.subTest(claim=claim):
                refused = self.refuse_init([self.task(claims={"suite": claim})])
                self.assertEqual(refused["code"], "schema_invalid", refused)

    def test_unstartable_trusted_verifier_holds_for_a_human(self):
        broken = self.project / "broken-verifier"
        broken.write_text("#!/nonexistent/interpreter\n")
        broken.chmod(0o755)
        self.init([self.task(claims={"suite": {"check": [str(broken)], "timeout_seconds": 5}}, files_changed=[])])
        self.turn()
        self.verifier_receipt()
        held = self.turn()
        self.assertEqual(held["action"], "escalate", held)
        self.assertIn("could not start", (self.root / held["evidence"]).read_text())

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.project), "-c", "user.name=fixture",
                               "-c", "user.email=fixture@example.invalid", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def git_project(self):
        self.git("init", "-q")
        (self.project / ".gitignore").write_text("adapter-state/\n")
        self.git("add", "AGENTS.md", ".gitignore")
        self.git("commit", "-qm", "base")
        return self.git("rev-parse", "HEAD")

    def arm_hostile_git(self):
        """Repository config a member could write; every helper logs its name inside .git."""
        log, helper = self.project / ".git/fired.log", self.project / ".git/helper"
        helper.write_text(f'#!/bin/sh\necho "$1" >> {log}\n[ "$1" = clean ] && exec cat\nexit 1\n')
        helper.chmod(0o755)
        for key, value in (("filter.x.clean", f"{helper} clean"), ("filter.x.process", f"{helper} process"),
                           ("core.fsmonitor", f"{helper} fsmonitor"), ("diff.x.textconv", f"{helper} textconv"),
                           ("diff.x.command", f"{helper} command"), ("diff.external", f"{helper} external"),
                           ("core.checkStat", "minimal"), ("core.trustctime", "false")):
            self.git("config", key, value)
        (self.project / ".git/info").mkdir(exist_ok=True)
        (self.project / ".git/info/attributes").write_text("* filter=x diff=x\n")
        tracked = self.project / "AGENTS.md"
        tracked.write_bytes(tracked.read_bytes().swapcase())  # same size: only content can decide
        os.utime(tracked, (1577836800, 1577836800))
        subprocess.run(["git", "-C", str(self.project), "status", "--porcelain"], capture_output=True,
                       stdin=subprocess.DEVNULL, timeout=20)
        self.assertTrue(log.exists(), "fixture not armed: plain git status ran no helper")
        log.unlink()
        return log

    def test_git_evidence_runs_no_repository_configured_helpers(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        base = self.git_project()
        (self.project / "work.txt").write_text("partial\n")
        self.git("add", "work.txt")
        self.git("commit", "-qm", "partial work")
        head = self.git("rev-parse", "HEAD")
        log = self.arm_hostile_git()
        self.assertEqual(lead.git_head(str(self.project)), head)
        window = lead.git_window({"project_root": str(self.project)},
                                 {"active": "7", "git_base": {"7": base}})
        self.assertFalse(log.exists(), log.read_text() if log.exists() else "")
        self.assertEqual(window, {"base": base, "head": head, "base_is_ancestor": True,
                                  "commits_ahead": 1, "commits": [head],
                                  "worktree": "not collected: Git content comparison can run "
                                              "repository helpers"})

    def test_git_evidence_never_lazily_fetches_through_a_member_remote(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        base = self.git_project()
        (self.project / "work.txt").write_text("partial\n")
        self.git("add", "work.txt")
        self.git("commit", "-qm", "partial work")
        log, helper = self.project / ".git/fired.log", self.project / ".git/remote"
        helper.write_text(f"#!/bin/sh\necho remote >> {log}\nexit 1\n")
        helper.chmod(0o755)
        for key, value in (("core.repositoryformatversion", "1"), ("extensions.partialClone", "origin"),
                           ("remote.origin.url", f"ext::{helper} %S"), ("remote.origin.promisor", "true"),
                           ("protocol.ext.allow", "always")):
            self.git("config", key, value)
        missing = self.git("rev-parse", "HEAD")
        (self.project / ".git/objects" / missing[:2] / missing[2:]).unlink()
        subprocess.run(["git", "-C", str(self.project), "cat-file", "-t", missing], capture_output=True,
                       stdin=subprocess.DEVNULL, timeout=20)
        self.assertTrue(log.exists(), "fixture not armed: plain cat-file did not lazily fetch")
        log.unlink()
        for evidence in (lead.git_head(str(self.project)),
                         lead.git_window({"project_root": str(self.project)},
                                         {"active": "7", "git_base": {"7": base}})):
            self.assertFalse(log.exists(), evidence)

    def test_stop_records_the_git_window_since_dispatch_as_evidence(self):
        base = self.git_project()
        self.init()
        self.turn()
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["tasks"]["7"]["git_base"], {"7": base})
        (self.project / "work.txt").write_text("partial\n")
        self.git("add", "work.txt")
        self.git("commit", "-qm", "partial work")
        head = self.git("rev-parse", "HEAD")
        (self.project / "scratch.txt").write_text("uncommitted\n")
        self.ring("STOPPED 7 out of time")
        stopped = self.turn()
        self.assertEqual(stopped["action"], "stop")
        self.assertEqual(stopped["git"], {"base": base, "head": head, "base_is_ancestor": True,
                                          "commits_ahead": 1, "commits": [head],
                                          "worktree": "not collected: Git content comparison can run "
                                                      "repository helpers"})
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertEqual(state["tasks"]["7"]["status"], "stopped")

    def test_hold_outside_git_records_unavailable_evidence_and_still_escalates(self):
        self.init()
        self.turn()
        state = json.loads((self.root / "lead-state.json").read_text())
        self.assertTrue(state["tasks"]["7"]["git_base"]["7"].startswith("unavailable"))
        self.ring("HELD 7 needs approval")
        held = self.turn()
        self.assertEqual(held["action"], "escalate")
        self.assertTrue(held["git"].startswith("unavailable"), held["git"])

    # ---- Ticket 1: one generated current-state projection (decisions 1, 2) -----------------

    def current_state(self):
        text = (self.root / "state.md").read_text()
        self.assertIn("## Current state", text)
        return text.split("## Current state", 1)[1].split("\n## ", 1)[0]

    def table(self, heading):
        block = self.current_state().split("### " + heading, 1)[1].split("\n### ", 1)[0]
        rows = [[cell.strip() for cell in line.strip().strip("|").split("|")]
                for line in block.splitlines() if line.startswith("|")]
        return [dict(zip(rows[0], row)) for row in rows[2:]]

    def outcome(self, task="7"):
        return next(row for row in self.table("Outcomes") if row["task"] == task)

    def attention(self):
        block = self.current_state().split("### Lead attention needed", 1)[1].split("\n### ", 1)[0]
        return [line[2:] for line in block.splitlines() if line.startswith("- ")]

    def lead_state(self):
        return json.loads((self.root / "lead-state.json").read_text())

    def accept_seven(self):
        self.init()
        self.turn()
        self.receipt()
        self.assertEqual(self.turn()["action"], "accept")

    def evidence_note(self, name="review-note.md"):
        path = self.project / name
        path.write_text("review evidence fixture\n")
        return path

    def record_identity(self, kind="reviewed", identity="a" * 64, evidence=None, task="7",
                        attempt="7", by="lead", expected=0, **changes):
        params = {"record_root": str(self.root), "task": task, "attempt": attempt, "by": by,
                  "kind": kind, "identity": identity,
                  "evidence": str(evidence or self.evidence_note()), **changes}
        return self.command("record", params, expected=expected)

    def test_projection_leads_state_md_with_one_generated_row_per_outcome(self):
        self.init()
        self.turn()
        text = (self.root / "state.md").read_text()
        self.assertLess(text.index("## Current state"), text.index("## Mission"))
        self.assertEqual(text.count("## Current state"), 1)
        self.assertIn("7 | alpha | 7 | dispatching", self.sent_states[0], "task line still precedes the send")
        row = self.outcome("7")
        self.assertEqual((row["owner"], row["scope"], row["status"]),
                         ("alpha", "Write hello with a newline.", "sent"))
        self.assertTrue(row["source identity"].startswith("UNKNOWN"), row)
        self.assertEqual((row["reviewed identity"], row["installed identity"]), ("UNKNOWN", "UNKNOWN"))
        self.assertIn("## Progress log", text, "dated history stays readable below the projection")

    def test_projection_maps_accepted_to_implemented_without_renaming_the_enum(self):
        self.accept_seven()
        self.assertEqual(self.outcome("7")["status"], "implemented [accepted]")
        self.assertEqual(self.lead_state()["tasks"]["7"]["status"], "accepted")

    def test_projection_maps_pending_and_held_work_to_blocked_on_check(self):
        self.init()
        self.turn()
        with (self.root / "tasks/7.md").open("a") as stream:
            stream.write("\n## Return\nCloses: 7\n")
        self.assertEqual(self.turn()["action"], "receipt-pending")
        self.assertEqual(self.outcome("7")["status"], "blocked-on-check [review-pending]")
        self.assertIn("receipt", self.outcome("7")["open gate"].lower())

    def test_projection_renders_unknown_when_the_decisive_proof_is_missing(self):
        self.accept_seven()
        (self.root / "reviews/7.json").unlink()
        self.turn()
        row = self.outcome("7")
        self.assertEqual(row["status"], "UNKNOWN [accepted]")
        self.assertIn("review proof", row["open gate"])

    def test_projection_source_identity_names_the_git_base_and_the_receipts_claimed_revision(self):
        base = self.git_project()
        self.init()
        self.turn()
        self.receipt()
        self.turn()
        row = self.outcome("7")
        digest = hashlib.sha256(b"hello\n").hexdigest()
        self.assertIn(base[:12], row["source identity"])
        self.assertIn(digest[:12], row["source identity"])

    def test_record_appends_a_reviewed_identity_and_changes_no_scheduler_state(self):
        self.accept_seven()
        before = self.lead_state()
        calls = len(self.peer.requests)
        result = self.record_identity("reviewed", "b" * 64, by="human")["result"]
        self.assertEqual(result["action"], "identity-recorded")
        self.assertEqual(len(self.peer.requests), calls, "record never touches the socket")
        state = self.lead_state()
        entry = state["tasks"]["7"]["identities"][0]
        self.assertEqual((entry["kind"], entry["attempt"], entry["by"], entry["identity"]),
                         ("reviewed", "7", "human", "b" * 64))
        self.assertTrue(entry["evidence"] and entry["at"])
        self.assertEqual(state["tasks"]["7"]["status"], before["tasks"]["7"]["status"])
        row = self.outcome("7")
        self.assertIn("b" * 12, row["reviewed identity"])
        self.assertEqual(row["status"], "implemented [accepted]")
        again = self.record_identity("reviewed", "b" * 64, by="human")["result"]
        self.assertEqual(again["action"], "already-recorded")
        self.assertEqual(len(self.lead_state()["tasks"]["7"]["identities"]), 1)

    def test_record_bounded_gives_accepted_bounded_and_installed_gives_released(self):
        self.accept_seven()
        self.record_identity("bounded", "c" * 40)
        self.assertEqual(self.outcome("7")["status"], "accepted-bounded [accepted]")
        self.record_identity("installed", "d" * 64)
        row = self.outcome("7")
        self.assertEqual(row["status"], "released (bounded scope) [accepted]")
        self.assertIn("d" * 12, row["installed identity"])
        self.record_identity("reviewed", "b" * 64)
        self.assertEqual(self.outcome("7")["status"], "released (bounded scope) [accepted]")

    def test_record_installed_on_unaccepted_work_is_contradictory_and_renders_unknown(self):
        self.init()
        self.turn()
        self.record_identity("installed", "d" * 64)
        self.assertEqual(self.outcome("7")["status"], "UNKNOWN [sent]")
        self.assertEqual(self.lead_state()["tasks"]["7"]["status"], "sent")

    def test_record_refuses_unlisted_values_and_outside_evidence_before_writing(self):
        self.accept_seven()
        before = (self.root / "lead-state.json").read_bytes()
        outside = Path(tempfile.mkdtemp(prefix="outside-", dir="/tmp")) / "x.md"
        outside.write_text("x\n")
        cases = [
            ({"by": "robot"}, "schema_invalid"), ({"kind": "approved"}, "schema_invalid"),
            ({"identity": "not-a-digest"}, "schema_invalid"), ({"identity": "A" * 64}, "schema_invalid"),
            ({"task": "99", "attempt": "99"}, "unknown_task"), ({"attempt": "8"}, "attempt_mismatch"),
            ({"evidence": str(outside)}, "path_outside_record"),
            ({"evidence": str(self.project / "missing.md")}, "evidence_unavailable"),
            ({"extra": "field"}, "schema_invalid"),
        ]
        for changes, code in cases:
            with self.subTest(changes=changes):
                self.evidence_note()
                refused = self.record_identity(expected=1, **changes)
                self.assertEqual(refused["error"]["code"], code, refused)
        self.assertEqual((self.root / "lead-state.json").read_bytes(), before)

    def test_an_excluded_required_outcome_never_releases_dependent_work(self):
        self.add_member("beta", "scratch:p2")
        self.init([self.task("7"), self.task("8", owner="beta", after=["7"])])
        self.turn()
        self.ring("STOPPED 7 scope excluded")
        self.assertEqual(self.turn()["action"], "stop")
        self.record_identity("bounded", "c" * 64)
        self.record_identity("reviewed", "b" * 64)
        self.assertEqual(self.outcome("7")["status"], "stopped")
        self.record_identity("installed", "d" * 64)
        state = self.lead_state()
        self.assertEqual((state["tasks"]["7"]["status"], state["tasks"]["8"]["status"]),
                         ("stopped", "queued"))
        self.assertEqual(self.outcome("7")["status"], "UNKNOWN [stopped]")
        for shown in ("released", "accepted-bounded", "implemented"):
            self.assertNotIn(shown, self.outcome("7")["status"])
        self.assertIn("7 (stopped)", self.outcome("8")["open gate"])
        self.turn()  # the mission is failed; no turn may dispatch the dependent
        self.assertEqual(len(self.sent_states), 1)

    # ---- decisions 3, 4, 5: measurement fields, attention rows, the wake option ------------

    def age(self, path, seconds):
        """Backdate a file and return the mtime the lead will read, as the lead formats it."""
        stamp = time.time() - seconds
        os.utime(path, (stamp, stamp))
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()

    def test_measure_returned_at_is_the_first_sighting_mtime_even_if_the_member_rewrites_its_return(self):
        self.init()
        self.turn()
        with (self.root / "tasks/7.md").open("a") as stream:
            stream.write("\n## Return\nCloses: 7\n")
        first = self.age(self.root / "tasks/7.md", 1800)
        self.assertEqual(self.turn()["action"], "receipt-pending")
        self.assertEqual(self.lead_state()["tasks"]["7"]["returned_at"], {"7": first})
        path = self.root / "tasks/7.md"  # the member rewrites its return in place; the mtime moves
        path.write_text(path.read_text().replace("\n## Return\nCloses: 7\n", ""))
        self.receipt()
        self.assertEqual(self.turn()["action"], "accept")
        self.assertEqual(self.lead_state()["tasks"]["7"]["returned_at"], {"7": first})
        row = next(r for r in self.table("Attempts") if r["attempt"] == "7")
        self.assertEqual(row["returned"], first)
        self.assertRegex(row["time in review"], r"^30m\d\ds$")
        self.assertEqual((row["correction rounds"], row["human interventions"]), ("0", "0"))

    def test_measure_counts_correction_rounds_and_answered_escalations_per_attempt(self):
        self.init()
        self.turn()
        self.ring("HELD 7 needs approval")
        held = self.turn()
        self.assertEqual(held["action"], "escalate")
        self.command("answer", {"record_root": str(self.root), "escalation": held["escalation"],
                               "by": "fixture-human", "decision": "continue", "answer": "Continue."})
        self.assertEqual(self.turn()["action"], "human-answer")
        self.receipt(content=b"wrong\n")
        self.ring("DONE 7 tasks/7.md")
        self.assertEqual(self.turn()["action"], "correct")
        self.assertEqual(self.turn()["task"], "7.2")
        self.receipt("7.2")
        self.ring("DONE 7.2 tasks/7.2.md")
        self.assertEqual(self.turn()["action"], "accept")
        rows = {r["attempt"]: r for r in self.table("Attempts")}
        self.assertEqual((rows["7"]["correction rounds"], rows["7"]["human interventions"]), ("0", "1"))
        self.assertEqual((rows["7.2"]["correction rounds"], rows["7.2"]["human interventions"]), ("1", "0"))
        self.assertEqual(rows["7"]["accepted"], "UNKNOWN", "a failed attempt was never accepted")
        self.assertNotEqual(rows["7.2"]["accepted"], "UNKNOWN")
        self.assertNotEqual(rows["7"]["dispatched"], "UNKNOWN")

    def test_measure_values_the_lead_never_observed_stay_unknown(self):
        self.add_member("beta", "scratch:p2")
        self.init([self.task("7"), self.task("8", owner="beta", after=["7"])])
        queued = next(r for r in self.table("Attempts") if r["attempt"] == "8")
        self.assertEqual([queued[k] for k in ("dispatched", "returned", "accepted", "time in review")],
                         ["UNKNOWN"] * 4)

    def test_attention_names_an_idle_member_with_an_eligible_queued_task(self):
        self.add_member("beta", "scratch:p2")
        self.init([self.task("7", value=10), self.task("9", owner="beta", value=5)])
        self.assertEqual(self.turn()["task"], "7")
        rows = [r for r in self.attention() if r.startswith("idle member")]
        self.assertEqual(rows, ["idle member beta has eligible queued task 9; no lead turn has dispatched it"])
        self.assertEqual(self.turn()["task"], "9")
        self.assertEqual([r for r in self.attention() if r.startswith("idle member")], [])

    def done_waiting_behind_help(self, **first_task):
        self.add_member("beta", "scratch:p2")
        self.init([self.task("7", value=10, **first_task), self.task("9", owner="beta", value=5)])
        self.turn()
        self.turn()
        self.age(self.receipt("7"), 1800)
        self.ring("HELP 9 which greeting", pane="scratch:p2")
        self.assertEqual(self.turn()["action"], "answer-help", "HELP outranks the waiting DONE")

    def test_attention_names_a_done_return_unreviewed_for_longer_than_the_default_limit(self):
        self.done_waiting_behind_help()
        rows = [r for r in self.attention() if r.startswith("DONE 7")]
        self.assertEqual(len(rows), 1, self.attention())
        self.assertIn("not reviewed (limit 10m)", rows[0])
        self.assertRegex(rows[0], r"returned 30m\d\ds ago")
        self.assertEqual(self.turn()["action"], "accept")
        self.assertEqual([r for r in self.attention() if r.startswith("DONE")], [])

    def test_attention_done_limit_is_set_per_task_in_the_workflow_object(self):
        self.done_waiting_behind_help(workflow={"methodology": "lead-local", "attention_minutes": 60})
        self.assertEqual([r for r in self.attention() if r.startswith("DONE")], [])
        self.assertNotIn("attention_minutes", (self.root / "tasks/7.md").read_text(),
                         "a lead-side setting never travels in the brief")

    def test_attention_names_in_flight_work_with_no_wake_or_a_lapsed_deadline(self):
        self.init()
        self.turn()
        self.assertTrue(any("task 7 is in flight with no wake recorded" in r for r in self.attention()))
        self.assertIn("- Wake: NONE recorded", self.current_state())
        self.temp.cleanup()
        self.setUp()
        wake = {"mechanism": "wake.py in the lead pane", "deadline_seconds": 120}
        self.init(wake=wake)
        self.turn()
        self.assertFalse(any("in flight" in r for r in self.attention()), self.attention())
        self.assertIn("- Wake: wake.py in the lead pane; deadline 120s", self.current_state())
        state = self.lead_state()
        state["last_turn_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        (self.root / "lead-state.json").write_text(json.dumps(state))
        self.record_identity("reviewed", "e" * 64)  # re-renders the projection without a lead turn
        late = [r for r in self.attention() if "in flight" in r]
        self.assertEqual(len(late), 1, late)
        self.assertIn("past the 120s wake deadline (wake.py in the lead pane)", late[0])
        del state["last_turn_at"]
        (self.root / "lead-state.json").write_text(json.dumps(state))
        self.record_identity("reviewed", "f" * 64)
        self.assertIn("last lead turn is UNKNOWN", [r for r in self.attention() if "in flight" in r][0])

    def test_init_wake_is_validated_stored_and_refused_before_any_write(self):
        bad = [{"mechanism": "w", "deadline_seconds": 59}, {"mechanism": "w", "deadline_seconds": 3601},
               {"mechanism": "w", "deadline_seconds": True}, {"mechanism": "", "deadline_seconds": 60},
               {"mechanism": 7, "deadline_seconds": 60}, {"deadline_seconds": 60},
               {"mechanism": "w", "deadline_seconds": 60, "extra": 1}, "wake.py"]
        for wake in bad:
            with self.subTest(wake=wake):
                refused = self.command("init", self.init_params(wake=wake), expected=1)
                self.assertEqual(refused["error"]["code"], "schema_invalid")
                self.assertFalse(self.root.exists())
        wake = {"mechanism": "wake.py in the lead pane", "deadline_seconds": 3600}
        self.init(wake=wake)
        self.assertEqual(self.lead_state()["wake"], wake)

    def test_projection_renders_identically_for_identical_inputs_and_key_order(self):
        self.accept_seven()
        self.record_identity("reviewed", "b" * 64)
        sys.path.insert(0, str(CLI.parent))
        import lead
        state, now = self.lead_state(), datetime.now(timezone.utc)
        first = lead.render_current_state(self.root.resolve(), state, now)
        reordered = json.loads(json.dumps(state, sort_keys=True))
        self.assertEqual(first, lead.render_current_state(self.root.resolve(), reordered, now))
        self.assertEqual(first, lead.render_current_state(self.root.resolve(), state, now))
        self.assertIn(first.strip(), (self.root / "state.md").read_text().replace(
            self.current_state().split("- As of: ")[1].split("\n")[0], now.isoformat()))

    # ---- Attempt 1.2: the independent review's findings (A1-A8, O2); Astra's probes, as tests ----

    def refresh(self):
        """Re-render the projection from the saved state without a lead turn."""
        sys.path.insert(0, str(CLI.parent))
        import lead
        state = self.lead_state()
        with lead.record_lock(self.root.resolve()):
            lead.record(self.root.resolve(), state)

    def accept_corrected(self):
        """Attempt 7 fails its check, attempt 7.2 is accepted."""
        self.init()
        self.turn()
        self.receipt(content=b"wrong\n")
        self.assertEqual(self.turn()["action"], "correct")
        self.assertEqual(self.turn()["task"], "7.2")
        self.receipt("7.2")
        self.assertEqual(self.turn()["action"], "accept")

    def bounded_prerequisite(self):
        self.add_member("beta", "scratch:p2")
        self.init([self.task("7", outcome="Write hello and a rollback procedure."),
                   self.task("8", owner="beta", after=["7"],
                             outcome="Exercise the rollback procedure required from task 7.")])
        self.turn()
        self.receipt()
        self.assertEqual(self.turn()["action"], "accept")
        scope = self.evidence_note("bounded-scope.md")
        scope.write_text("Task 7 accepted scope: hello only. Required rollback procedure excluded.\n")
        self.record_identity("bounded", hashlib.sha256(scope.read_bytes()).hexdigest(), scope)

    def test_bounded_scope_does_not_release_excluded_prerequisite(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        self.bounded_prerequisite()
        self.assertEqual(self.outcome("7")["status"], "accepted-bounded [accepted]")
        action = self.turn()
        self.assertNotEqual(action["action"], "dispatch", "excluded prerequisite released task 8")
        self.assertEqual(len(self.sent_states), 1, "only task 7 was ever sent")
        state = self.lead_state()
        self.assertEqual(state["tasks"]["8"]["status"], "queued")
        self.assertEqual(lead.pick(state), [], "the scheduler holds task 8")
        row = self.outcome("8")
        self.assertEqual(row["open gate"], "waits on 7 (accepted-bounded)")
        self.assertTrue(row["next permitted action"].startswith("none"), row)
        self.assertFalse([r for r in self.attention() if r.startswith("idle member")], self.attention())
        self.record_identity("installed", "d" * 64)  # installing the bounded scope does not widen it
        self.turn()
        self.assertEqual(len(self.sent_states), 1)
        self.assertEqual(self.outcome("8")["open gate"], "waits on 7 (accepted-bounded)")

    def test_installed_bounded_scope_keeps_scope_warning(self):
        self.bounded_prerequisite()
        self.assertIn("bounded scope revision recorded; not the full scope", self.outcome("7")["open gate"])
        self.record_identity("reviewed", "b" * 64)
        self.record_identity("installed", "d" * 64)
        row = self.outcome("7")
        self.assertEqual(row["status"], "released (bounded scope) [accepted]")
        self.assertIn("bounded scope revision recorded; not the full scope", row["open gate"])
        self.assertIn("bounded-scope.md", row["open gate"], "the note naming the excluded scope stays visible")
        self.assertEqual(row["scope"], "Write hello and a rollback procedure.")

    def test_missing_install_evidence_cannot_remain_released(self):
        self.accept_seven()
        evidence = self.evidence_note("install-proof.md")
        self.record_identity("reviewed", "a" * 64, evidence)
        self.record_identity("installed", "a" * 64, evidence)
        self.assertEqual(self.outcome("7")["status"], "released [accepted]")
        evidence.unlink()
        self.refresh()
        row = self.outcome("7")
        self.assertEqual(row["status"], "UNKNOWN [accepted]")
        self.assertEqual(row["open gate"], "evidence missing or changed")

    def test_record_stores_the_evidence_digest_and_a_changed_file_renders_unknown_until_restored(self):
        self.accept_seven()
        evidence = self.evidence_note("install-proof.md")
        self.record_identity("reviewed", "a" * 64, evidence)
        self.record_identity("installed", "a" * 64, evidence)
        stored = self.lead_state()["tasks"]["7"]["identities"]
        self.assertEqual({row["evidence_sha256"] for row in stored}, {hashlib.sha256(evidence.read_bytes()).hexdigest()})
        original = evidence.read_bytes()
        evidence.write_text("someone edited the proof after it was recorded\n")
        self.refresh()
        self.assertEqual((self.outcome("7")["status"], self.outcome("7")["open gate"]),
                         ("UNKNOWN [accepted]", "evidence missing or changed"))
        evidence.write_bytes(original)
        self.refresh()
        self.assertEqual(self.outcome("7")["status"], "released [accepted]")
        outside = Path(tempfile.mkdtemp(prefix="outside-", dir="/tmp")) / "same.md"
        outside.write_bytes(original)
        evidence.unlink()
        evidence.symlink_to(outside)  # the same bytes, but no longer a file under the declared roots
        self.refresh()
        self.assertEqual(self.outcome("7")["status"], "UNKNOWN [accepted]")

    def test_wrong_attempt_review_proof_is_unknown(self):
        self.accept_seven()
        proof = self.root / "reviews/7.json"
        valid = json.loads(proof.read_text())
        for changes in ({"attempt": "8"}, {"receipt": "tasks/8.md"}, {"attempt": "8", "receipt": "tasks/8.md"}):
            with self.subTest(changes=changes):
                proof.write_text(json.dumps({**valid, **changes}))
                self.refresh()
                row = self.outcome("7")
                self.assertEqual(row["status"], "UNKNOWN [accepted]")
                self.assertIn("review proof", row["open gate"])
                attempt = next(r for r in self.table("Attempts") if r["attempt"] == "7")
                self.assertEqual((attempt["accepted"], attempt["time in review"]), ("UNKNOWN", "UNKNOWN"))
        proof.write_text(json.dumps(valid))
        self.refresh()
        self.assertEqual(self.outcome("7")["status"], "implemented [accepted]")

    def test_future_install_record_cannot_release_later_attempt(self):
        self.init()
        refused = self.record_identity("installed", "d" * 64, attempt="7.2", expected=1)
        self.assertEqual(refused["error"]["code"], "unknown_attempt")
        self.assertNotIn("identities", self.lead_state()["tasks"]["7"])
        self.turn()
        self.receipt(content=b"wrong\n")
        self.assertEqual(self.turn()["action"], "correct")
        self.assertEqual(self.turn()["task"], "7.2")
        self.receipt("7.2")
        self.assertEqual(self.turn()["action"], "accept")
        self.assertNotIn("released", self.outcome("7")["status"], "installation was recorded before attempt 7.2 existed")
        self.assertEqual(self.record_identity("reviewed", "b" * 64, attempt="7")["result"]["action"],
                         "identity-recorded", "an attempt in this task's history can still be recorded")
        self.assertEqual(self.record_identity("reviewed", "c" * 64, attempt="7.2")["result"]["action"],
                         "identity-recorded")
        self.assertEqual(self.record_identity("reviewed", "c" * 64, attempt="7.3", expected=1)["error"]["code"],
                         "unknown_attempt")

    def test_a_rejected_doorbell_does_not_create_an_attempt_to_record_against(self):
        self.init()
        self.turn()
        self.ring("DONE 7.5 tasks/7.5.md")
        self.assertEqual(self.turn()["action"], "reject-doorbell")
        refused = self.record_identity("installed", "d" * 64, attempt="7.5", expected=1)
        self.assertEqual(refused["error"]["code"], "unknown_attempt")
        self.assertEqual([r["attempt"] for r in self.table("Attempts")], ["7"])

    def test_parent_note_does_not_expand_evidence_roots(self):
        with tempfile.TemporaryDirectory(prefix="outside-", dir="/tmp") as directory:
            outside = Path(directory).resolve()
            note = outside / "state.md"
            workflow = self.matt_workflow()
            note.write_bytes(Path(workflow["state"]).read_bytes())
            workflow["state"] = str(note)
            self.init([self.task(workflow=workflow)])
            unrelated = outside / "unrelated.txt"
            unrelated.write_text("Not evidence authorized under the record root or its parent.\n")
            before = (self.root / "lead-state.json").read_bytes()
            refused = self.record_identity(evidence=unrelated, expected=1)
            self.assertEqual(refused["error"]["code"], "path_outside_record")
            self.assertEqual((self.root / "lead-state.json").read_bytes(), before)
            inside = self.root / "reviews-note.md"
            inside.write_text("inside the record root\n")
            self.assertEqual(self.record_identity(evidence=inside)["result"]["action"], "identity-recorded")
            self.assertEqual(self.record_identity("installed", "d" * 64)["result"]["action"], "identity-recorded",
                             "the record root's parent directory is the one other root")

    def test_changed_brief_without_closes_does_not_create_return_timestamp(self):
        self.init()
        self.turn()
        path = self.root / "tasks/7.md"
        path.write_text(path.read_text().replace("Write hello", "Write goodbye", 1))
        self.assertNotIn("Closes:", path.read_text())
        action = self.turn()
        self.assertEqual(action["action"], "receipt-refused", "an unjudgeable return still goes to review")
        self.assertEqual(self.lead_state()["tasks"]["7"].get("returned_at", {}), {})
        row = next(r for r in self.table("Attempts") if r["attempt"] == "7")
        self.assertEqual(row["returned"], "UNKNOWN")

    def test_queued_busy_owner_is_not_told_dispatch_permitted(self):
        self.init([self.task("7"), self.task("8", after=[])])
        self.turn()
        row = self.outcome("8")
        self.assertEqual(row["next permitted action"], "wait for alpha to finish task 7")

    def test_next_permitted_action_says_dispatch_exactly_when_the_scheduler_would(self):
        sys.path.insert(0, str(CLI.parent))
        import lead
        self.add_member("beta", "scratch:p2")
        self.add_member("gamma", "scratch:p3")
        self.init([self.task("7"), self.task("8", after=[]), self.task("9", owner="beta", after=["7"]),
                   self.task("10", owner="gamma")])
        self.turn()
        state = self.lead_state()
        dispatch = "dispatch on the next lead turn"
        shown = {t: self.outcome(t)["next permitted action"] == dispatch for t in ("8", "9", "10")}
        self.assertEqual(shown, {t: lead.assignable(state, state["tasks"][t]) for t in ("8", "9", "10")})
        self.assertEqual(shown, {"8": False, "9": False, "10": True})

    def test_installed_without_a_recorded_review_adds_a_gate_and_leaves_the_status(self):
        self.accept_seven()
        self.record_identity("installed", "d" * 64)
        row = self.outcome("7")
        self.assertEqual(row["status"], "released [accepted]")
        self.assertEqual(row["open gate"], "installed without a recorded review")
        self.record_identity("reviewed", "b" * 64)
        row = self.outcome("7")
        self.assertEqual((row["status"], row["open gate"]), ("released [accepted]", "none"))

    def test_a_review_of_an_earlier_attempt_does_not_cover_the_installed_attempt(self):
        self.accept_corrected()
        self.record_identity("reviewed", "b" * 64, attempt="7")
        self.record_identity("installed", "d" * 64, attempt="7.2")
        self.assertEqual(self.outcome("7")["open gate"], "installed without a recorded review")
        self.record_identity("reviewed", "c" * 64, attempt="7.2")
        self.assertEqual(self.outcome("7")["open gate"], "none")

    # ---- Ticket 2: attention rows for a silent owner, assignment pins and a bounded hold -------------

    def rerender(self):
        """Re-render the projection without a lead turn: any new identity entry does it."""
        self._renders = getattr(self, "_renders", 0) + 1
        self.record_identity("reviewed", f"{self._renders:064x}")

    def dispatched_ago(self, minutes, task="7"):
        state = self.lead_state()
        for entry in state["progress"]:
            if entry.get("action") == "dispatch" and entry.get("task") == task:
                entry["at"] = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        (self.root / "lead-state.json").write_text(json.dumps(state))

    def owner_rows(self):
        return [r for r in self.attention() if r.startswith("owner ")]

    def test_attention_names_an_idle_owner_whose_task_has_no_closing_return_past_the_limit(self):
        self.init()
        self.turn()
        self.dispatched_ago(5)
        self.rerender()
        self.assertEqual(self.owner_rows(), [], "inside attention_minutes the owner is simply between steps")
        self.dispatched_ago(30)
        self.rerender()
        rows = self.owner_rows()
        self.assertEqual(len(rows), 1, self.attention())
        self.assertRegex(rows[0], r"^owner alpha is idle while task 7 has no return closing it "
                                  r"\(dispatched 30m\d\ds ago, limit 10m\)")
        self.assertIn("/clear", rows[0], "the blind spot is named: a cleared or replaced session looks the same")
        self.snapshot["agents"][0]["agent_status"] = "done"
        self.turn()
        self.assertTrue(self.owner_rows()[0].startswith("owner alpha is done while task 7"), self.attention())
        self.snapshot["agents"][0]["agent_status"] = "working"
        self.turn()
        self.assertEqual(self.owner_rows(), [], "a working owner is not silent")

    def silent_owner_rows(self, status):
        """Owner rows when the owner of a task dispatched 30 minutes ago reports this Herdr status."""
        self.init()
        self.turn()
        self.dispatched_ago(30)
        self.snapshot["agents"][0]["agent_status"] = status
        self.turn()
        return self.owner_rows()

    def test_attention_names_a_blocked_owner_and_says_to_look_at_the_dialog_not_type_into_it(self):
        self.init()
        self.turn()
        self.dispatched_ago(5)
        self.snapshot["agents"][0]["agent_status"] = "blocked"
        self.turn()
        self.assertEqual(self.owner_rows(), [], "inside attention_minutes a dialog may just have opened")
        self.dispatched_ago(30)
        self.rerender()
        rows = self.owner_rows()
        self.assertEqual(len(rows), 1, self.attention())
        self.assertRegex(rows[0], r"^owner alpha is blocked while task 7 has no return closing it "
                                  r"\(dispatched 30m\d\ds ago, limit 10m\)")
        self.assertIn("dialog only a human answers", rows[0])
        self.assertIn("never type into it", rows[0])

    def test_attention_names_an_owner_whose_herdr_status_is_unknown(self):
        rows = self.silent_owner_rows("unknown")
        self.assertEqual(len(rows), 1, self.attention())
        self.assertRegex(rows[0], r"^owner alpha has Herdr status unknown while task 7 has no return closing it "
                                  r"\(dispatched 30m\d\ds ago, limit 10m\)")
        self.assertIn("Herdr cannot tell what the pane is doing", rows[0])

    def test_attention_names_an_owner_whose_status_the_schema_does_not_list(self):
        rows = self.silent_owner_rows("paused")
        self.assertEqual(len(rows), 1, self.attention())
        self.assertRegex(rows[0], r"^owner alpha reports the unrecognised Herdr status 'paused' while task 7 ")
        self.assertIn("look at the pane", rows[0])

    def test_attention_leaves_a_working_owner_alone(self):
        self.assertEqual(self.silent_owner_rows("working"), [])

    def test_every_agent_status_in_the_schema_has_an_attention_test(self):
        schema = json.loads((CLI.parent / "api-schema.json").read_text())
        statuses = schema["schemas"]["success_response"]["$defs"]["AgentStatus"]["enum"]
        # idle and done: the idle-owner test above; blocked, unknown and working: their own tests; a new Herdr
        # status fails here until it is decided in lead.py's OWNER_ROWS and tested.
        self.assertEqual(sorted(statuses), ["blocked", "done", "idle", "unknown", "working"])

    def test_an_interrupted_or_cleared_worker_leaves_the_task_pending_and_is_flagged_not_accepted(self):
        # Esc and /clear never run a Stop hook, so no hook output exists at all. The attempt must stay unaccepted
        # and the silence must reach the lead as an attention row, whatever the pane does next.
        self.init()
        self.turn()
        self.dispatched_ago(45)
        self.snapshot["agents"][0]["agent_status"] = "idle"  # the fresh session after /clear sits at its prompt
        for _ in range(3):
            self.assertNotEqual(self.turn()["action"], "accept")
        state = self.lead_state()
        self.assertEqual((state["tasks"]["7"]["status"], state["tasks"]["7"]["active"]), ("sent", "7"))
        self.assertFalse((self.root / "reviews").exists())
        self.assertEqual(len(self.owner_rows()), 1, self.attention())

    def test_attention_owner_row_honours_the_per_task_limit_and_a_closing_return(self):
        self.init([self.task("7", workflow={"methodology": "lead-local", "attention_minutes": 60})])
        self.turn()
        self.dispatched_ago(30)
        self.rerender()
        self.assertEqual(self.owner_rows(), [], "attention_minutes 60 is the limit for this task")
        self.temp.cleanup()
        self.setUp()
        self.init()
        self.turn()
        self.dispatched_ago(30)
        self.receipt()  # the return closes the attempt, so the owner is not silent; the DONE row covers review
        self.rerender()
        self.assertEqual(self.owner_rows(), [], self.attention())

    def test_attention_owner_row_says_unknown_when_the_dispatch_time_is_unreadable(self):
        self.init()
        self.turn()
        state = self.lead_state()
        for entry in state["progress"]:
            if entry.get("action") == "dispatch":
                entry["at"] = "not a time"
        (self.root / "lead-state.json").write_text(json.dumps(state))
        self.rerender()
        rows = self.owner_rows()
        self.assertEqual(len(rows), 1, self.attention())
        self.assertIn("dispatch time UNKNOWN", rows[0])

    def pin(self, pane, attempt="3", name="manual-3.md", minutes=30, close=False, raw=None):
        """An assignment pin: the dispatch record the manual path writes at dispatch."""
        (self.root / "assignments").mkdir(exist_ok=True)
        back = self.project / name
        back.write_text(f"---\ntask: {attempt.split('.')[0]}\nattempt: {attempt}\n---\n# Brief\n")
        if close:
            with back.open("a") as stream:
                stream.write(f"\n## Return — attempt {attempt}\n\nCloses: {attempt}\n")
        stamp = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        text = raw if raw is not None else json.dumps({"return": str(back), "attempt": attempt, "matt": False,
                                                       "dispatched_at": stamp})
        path = self.root / "assignments" / (pane + ".json")
        path.write_text(text)
        return path

    def test_attention_covers_assignment_pins_in_a_lead_record(self):
        self.add_member("beta", "scratch:p2")
        self.init()  # beta is a member of the record with no lead task, so a pin is its only assignment
        self.turn()
        self.pin("scratch:p2")
        self.rerender()
        rows = [r for r in self.attention() if "assignment pin" in r]
        self.assertEqual(len(rows), 1, self.attention())
        self.assertRegex(rows[0], r"^owner beta is idle while assignment pin scratch:p2 \(attempt 3\) has no "
                                  r"return closing it \(dispatched 30m\d\ds ago, limit 10m\)")
        self.pin("scratch:p2", close=True)
        self.rerender()
        self.assertEqual([r for r in self.attention() if "assignment pin" in r], [], "a closing return clears it")
        self.pin("scratch:p2", minutes=2)
        self.rerender()
        self.assertEqual([r for r in self.attention() if "assignment pin" in r], [], "inside the limit")

    def test_attention_pin_for_a_pane_the_record_cannot_observe_says_unknown_not_idle(self):
        self.init()
        self.turn()
        self.pin("elsewhere:p9")
        self.rerender()
        rows = [r for r in self.attention() if "assignment pin" in r]
        self.assertEqual(len(rows), 1, self.attention())
        self.assertIn("owner status UNKNOWN (pane is not a member of this record)", rows[0])
        self.assertNotIn(" is idle", rows[0])

    def test_attention_names_an_unreadable_or_malformed_assignment_pin(self):
        self.init()
        self.turn()
        self.pin("scratch:p1", raw="{not json")
        self.pin("scratch:p2", raw=json.dumps({"return": "relative.md", "attempt": "3"}))
        self.rerender()
        rows = [r for r in self.attention() if "assignment pin" in r]
        self.assertEqual(len(rows), 2, self.attention())
        self.assertTrue(all("UNKNOWN" in r and "unreadable or malformed" in r for r in rows), rows)

    def test_a_bounded_hold_is_announced_in_attention_and_never_sits_silent(self):
        self.bounded_prerequisite()
        held = [r for r in self.attention() if r.startswith("dependent")]
        self.assertEqual(held, ["dependent 8 held by accepted-bounded predecessor 7; a human decides"])
        self.turn()
        self.assertEqual([r for r in self.attention() if r.startswith("dependent")], held,
                         "no lead turn lifts the hold, so the row stays")
        self.assertEqual(len(self.sent_states), 1, "task 8 was never sent")

    def swap_during_digest(self, evidence, swap):
        """Run swap() inside the digest of this evidence, after the lead has resolved and checked its path."""
        from unittest.mock import patch
        sys.path.insert(0, str(CLI.parent))
        import lead
        original_path, original_digest, swapped = evidence.resolve(), lead.BoundedReader.digest, []

        def swap_then_digest(reader, path):
            if Path(path) == original_path and not swapped:
                swap()
                swapped.append(True)
            return original_digest(reader, path)

        with patch.object(lead.BoundedReader, "digest", swap_then_digest):
            self.refresh()  # in-process, so the patch applies; rerender() runs lead.py as a subprocess
        self.assertTrue(swapped, "the swap point was never reached")

    def test_evidence_swapped_for_a_symlink_after_the_root_check_is_unknown(self):
        # N1: the check and the read must act on the same opened object, never on two resolutions of a path.
        self.accept_seven()
        evidence = self.evidence_note("install-proof.md")
        self.record_identity("installed", "d" * 64, evidence)
        self.assertEqual(self.outcome()["status"], "released [accepted]")
        with tempfile.TemporaryDirectory(prefix="outside-evidence-") as directory:
            outside = Path(directory) / "same-proof.md"
            outside.write_bytes(evidence.read_bytes())

            def swap():
                evidence.unlink()
                evidence.symlink_to(outside)
            self.swap_during_digest(evidence, swap)
            row = self.outcome()
            self.assertIn("UNKNOWN", row["status"])
            self.assertEqual(row["open gate"], "evidence missing or changed")

    def test_evidence_directory_swapped_for_a_symlink_after_the_root_check_is_unknown(self):
        # The final component is a regular file, so O_NOFOLLOW alone passes; the descriptor's real path must be checked.
        self.accept_seven()
        folder = self.project / "proofs"
        folder.mkdir()
        evidence = folder / "install-proof.md"
        evidence.write_text("review evidence fixture\n")
        self.record_identity("installed", "d" * 64, evidence)
        self.assertEqual(self.outcome()["status"], "released [accepted]")
        with tempfile.TemporaryDirectory(prefix="outside-evidence-") as directory:
            (Path(directory) / "install-proof.md").write_bytes(evidence.read_bytes())

            def swap():
                folder.rename(self.project / "proofs-moved")
                folder.symlink_to(directory)
            self.swap_during_digest(evidence, swap)
            self.assertIn("UNKNOWN", self.outcome()["status"])

    def test_evidence_still_released_when_nothing_moves(self):
        self.accept_seven()
        evidence = self.evidence_note("install-proof.md")
        self.record_identity("installed", "d" * 64, evidence)
        self.rerender()
        self.assertEqual(self.outcome()["status"], "released [accepted]")

    def test_no_bounded_hold_row_for_an_ordinary_dependency(self):
        self.add_member("beta", "scratch:p2")
        self.init([self.task("7"), self.task("8", owner="beta", after=["7"])])
        self.turn()
        self.assertEqual([r for r in self.attention() if r.startswith("dependent")], [], "queued behind a sent task")
        self.receipt()
        self.assertEqual(self.turn()["action"], "accept")
        self.assertEqual([r for r in self.attention() if r.startswith("dependent")], [], "released, not held")

if __name__ == "__main__":
    unittest.main()
