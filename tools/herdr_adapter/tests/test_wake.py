"""wake.py: the caller-side waiter. It observes and journals; it never sends, dispatches or accepts."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest

import test_lead

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lead

WAKE = Path(__file__).resolve().parents[1] / "wake.py"
SEND_OR_READ = {"pane.send_input", "pane.read", "pane.send_keys"}


def run_wake(test, params, expected=0):
    """A module function, not a method: other test classes borrow WakeTest.wake and need nothing else from it."""
    result = subprocess.run(
        [sys.executable, str(WAKE), "--socket", test.peer.path],
        input=json.dumps({"command": "wake", "params": params}),
        text=True, capture_output=True, timeout=60)
    test.assertEqual(result.returncode, expected, result.stdout + result.stderr[-400:])
    response = json.loads(result.stdout)
    return response["result"] if expected == 0 else response


class WakeTest(unittest.TestCase):
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
    age = test_lead.LeadTest.age

    def wake(self, max_seconds=30, slice_seconds=0.2, expected=0, **params):
        return run_wake(self, {"record_root": str(self.root), "max_seconds": max_seconds,
                               "slice_seconds": slice_seconds, **params}, expected)

    # ---- attempt 1.2 (G1): the manual path names its return files instead of a lead record ----

    def brief_file(self, name="9.2.md", attempt="9.2"):
        path = self.project / name
        path.write_text(f"---\ntask: {attempt.split('.')[0]}\nattempt: {attempt}\nowner: kai\nlatitude: own\n"
                        f"kind: build\nreturn: {path}\n---\n# Brief\n\n## Why\nNeeds a return.\n\n"
                        "## Return\nWrite the return below this brief, then ring the doorbell.\n")
        return path

    def close(self, path, attempt, text=""):
        with path.open("a") as stream:
            stream.write(f"\n## Return — attempt {attempt}\n\nCloses: {attempt}\n\n### Result\nDone.\n{text}")

    def wake_returns(self, returns, max_seconds=30, slice_seconds=0.2, expected=0, **params):
        return run_wake(self, {"returns": returns, "max_seconds": max_seconds,
                               "slice_seconds": slice_seconds, **params}, expected)

    def test_returns_mode_does_not_wake_for_a_closes_line_with_no_receipt_heading(self):
        # split_returns falls back to the whole text when no heading starts a receipt; that fallback section has
        # an empty label, and closed_returns must not treat a bare Closes line in it as a return.
        front = "---\ntask: 9\nattempt: 9.2\nowner: kai\nlatitude: own\nkind: build\nreturn: {}\n---\n"
        elsewhere = self.project / "closes-in-why.md"
        elsewhere.write_text(front.format(elsewhere) + "# Brief\n\n## Why\nCloses: 9.2\n\n"
                             "## Return\nWrite the return below this brief, then ring the doorbell.\n")
        headingless = self.project / "no-heading.md"
        headingless.write_text(front.format(headingless) + "# Brief\n\nCloses: 9.2\n")
        for path in (elsewhere, headingless):
            with self.subTest(path=path.name):
                woke = self.wake_returns([{"path": str(path), "attempt": "9.2"}], max_seconds=1, slice_seconds=0.3)
                self.assertEqual((woke["reason"], woke["changes"]["returns"]), ("deadline", []), woke)
        self.close(elsewhere, "9.2")  # control: a real '## Return — attempt 9.2' section does wake
        woke = self.wake_returns([{"path": str(elsewhere), "attempt": "9.2"}], max_seconds=30)
        self.assertEqual(woke["reason"], "new_return", woke)

    def test_returns_mode_does_not_read_a_fenced_example_as_a_return_section(self):
        # N2: a Markdown example of a receipt inside a code fence is documentation, not a return.
        front = "---\ntask: 9\nattempt: 9\nowner: kai\nlatitude: own\nkind: build\nreturn: {}\n---\n# Brief\n"
        examples = {
            "backticks": "```markdown\n## Return — attempt 9\nCloses: 9\n```\n",
            "tildes": "~~~\n## Return — attempt 9\nCloses: 9\n~~~\n",
            "longer-fence-with-inner-fence": "````markdown\n```\n## Return — attempt 9\nCloses: 9\n```\n````\n",
            "unclosed-fence": "```markdown\n## Return — attempt 9\nCloses: 9\n",
        }
        for name, example in examples.items():
            path = self.project / f"fenced-{name}.md"
            path.write_text(front.format(path) + "\n## Example only\n" + example)
            with self.subTest(fence=name):
                woke = self.wake_returns([{"path": str(path), "attempt": "9"}], max_seconds=1, slice_seconds=0.3)
                self.assertEqual((woke["reason"], woke["changes"]["returns"]), ("deadline", []), woke)

    def test_returns_mode_still_wakes_for_a_real_return_that_contains_a_fenced_block(self):
        path = self.brief_file("9.md", "9")
        self.close(path, "9", "\n```sh\n## not a heading\n```\n")
        with path.open("a") as stream:
            stream.write("\n```markdown\n## Return\nCloses: 8\n```\n")
        woke = self.wake_returns([{"path": str(path), "attempt": "9"}], max_seconds=30)
        self.assertEqual(woke["reason"], "new_return", woke)

    def flip_pane_later(self, delay):
        def flip():
            agent = self.snapshot["agents"][0]
            agent["agent_status"] = "working"
            agent["state_change_seq"] += 1
        timer = threading.Timer(delay, flip)
        timer.start()
        self.addCleanup(timer.cancel)

    def move_pane_after_the_first_look(self):
        """Returns mode takes its baseline from the waiter's own first look, so a pane that moved before a slowly
        starting waiter looked would never read as a change. Each snapshot after the first shows the pane working
        and newer, whenever that first look comes."""
        reply, looks = self.peer.reply, []

        def moving(request):
            if request["method"] == "session.snapshot":
                if looks:
                    agent = self.snapshot["agents"][0]
                    agent["agent_status"] = "working"
                    agent["state_change_seq"] += 1
                looks.append(request)
            return reply(request)
        self.peer.reply = moving

    def test_a_receipt_only_completion_with_an_unchanged_pane_wakes_the_lead(self):
        self.init(wake={"mechanism": "wake.py in the lead pane", "deadline_seconds": 60})
        self.turn()
        self.receipt()  # no doorbell, no pane change: the AMEND 1 case
        started, calls = time.monotonic(), len(self.peer.requests)
        woke = self.wake(max_seconds=30)
        self.assertEqual(woke["reason"], "new_return", woke)
        self.assertFalse({r["method"] for r in self.peer.requests[calls:]} & SEND_OR_READ)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual([(r["task"], r["attempt"]) for r in woke["changes"]["returns"]], [("7", "7")])
        self.assertTrue(woke["journaled"])
        self.assertEqual(self.lead_state()["last_wake"]["reason"], "new_return")
        self.assertEqual(self.turn()["action"], "accept", "the next lead turn finds the receipt on disk")
        self.assertRegex((self.root / "state.md").read_text(), r"- Last wake: \S+ \(new_return\)")

    def test_a_pane_status_change_since_the_leads_last_look_wakes_the_lead(self):
        self.init()
        self.turn()
        self.flip_pane_later(0.5)
        woke = self.wake(max_seconds=30, slice_seconds=0.3)
        self.assertEqual(woke["reason"], "pane_status", woke)
        change = woke["changes"]["panes"][0]
        self.assertEqual((change["pane_id"], change["after"]["agent_status"]), ("scratch:p1", "working"))

    def test_the_deadline_wakes_the_lead_when_nothing_changes(self):
        self.init()
        self.turn()
        started = time.monotonic()
        woke = self.wake(max_seconds=1, slice_seconds=0.3)
        self.assertEqual(woke["reason"], "deadline")
        self.assertEqual(woke["changes"], {"panes": [], "returns": []})
        self.assertTrue(1 <= time.monotonic() - started < 8)

    def test_a_return_revision_the_lead_already_reviewed_is_not_new(self):
        self.init()
        self.turn()
        with (self.root / "tasks/7.md").open("a") as stream:
            stream.write("\n## Return\nCloses: 7\n")
        self.assertEqual(self.turn()["action"], "receipt-pending")
        self.assertEqual(self.wake(max_seconds=1, slice_seconds=0.3)["reason"], "deadline")
        with (self.root / "tasks/7.md").open("a") as stream:
            stream.write("\nmore text\n")
        self.assertEqual(self.wake(max_seconds=30)["reason"], "new_return")

    def test_wake_never_sends_input_dispatches_or_accepts(self):
        self.init()
        self.turn()
        self.flip_pane_later(0.3)
        before = (self.lead_state()["tasks"]["7"]["status"], len(self.sent_states))
        calls = len(self.peer.requests)
        self.wake(max_seconds=30, slice_seconds=0.3)
        methods = {r["method"] for r in self.peer.requests[calls:]}
        self.assertTrue(methods and not methods & SEND_OR_READ, methods)
        self.assertEqual((self.lead_state()["tasks"]["7"]["status"], len(self.sent_states)), before)
        self.assertFalse((self.root / "reviews").exists())

    def test_wake_refuses_bad_params_before_any_socket_call(self):
        self.init()
        self.turn()
        calls = len(self.peer.requests)
        for params in ({"max_seconds": 0}, {"max_seconds": 3601}, {"max_seconds": "9"},
                       {"max_seconds": True}, {"slice_seconds": 61}, {"slice_seconds": 0},
                       {"surprise": 1}):
            with self.subTest(params=params):
                self.assertEqual(self.wake(expected=1, **params)["error"]["code"], "schema_invalid")
        self.assertEqual(len(self.peer.requests), calls)

    def test_a_busy_record_lock_does_not_stop_the_wake_from_reporting(self):
        self.init()
        self.turn()
        self.receipt()
        with lead.record_lock(self.root.resolve()):
            woke = self.wake(max_seconds=30)
        self.assertEqual((woke["reason"], woke["journaled"]), ("new_return", False))
        self.assertNotIn("last_wake", self.lead_state())

    def test_returns_mode_wakes_when_a_listed_file_gains_a_matching_closes_suffix_mid_wait(self):
        path = self.brief_file()
        before, calls = path.read_bytes(), len(self.peer.requests)
        timer = threading.Timer(0.5, self.close, (path, "9.2"))
        timer.start()
        self.addCleanup(timer.join)
        started = time.monotonic()
        woke = self.wake_returns([{"path": str(path), "attempt": "9.2"}], max_seconds=30)
        self.assertEqual(woke["reason"], "new_return", woke)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual([(r["path"], r["attempt"]) for r in woke["changes"]["returns"]], [(str(path), "9.2")])
        self.assertEqual(woke["changes"]["returns"][0]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(woke["changes"]["panes"], [])
        self.assertFalse(woke["journaled"])
        self.assertEqual(len(self.peer.requests), calls, "no workspace_id: not one socket call")
        self.assertFalse(self.root.exists(), "no lead record is read or written")
        self.assertTrue(path.read_bytes().startswith(before), "the brief prefix is untouched")

    def test_returns_mode_sees_a_matching_return_that_is_already_on_disk_at_once(self):
        path = self.brief_file()
        self.close(path, "9.2")
        started = time.monotonic()
        woke = self.wake_returns([{"path": str(path), "attempt": "9.2"}], max_seconds=30, slice_seconds=5)
        self.assertEqual(woke["reason"], "new_return")
        self.assertLess(time.monotonic() - started, 4)

    def test_returns_mode_deadline_and_returns_that_do_not_match_the_listed_attempt(self):
        path = self.brief_file()
        self.assertNotIn("Closes:", path.read_text(), "the brief's own Return section carries no Closes line")
        other = self.brief_file("9.md", "9")
        self.close(other, "9")  # an earlier attempt's return, in another file
        self.close(path, "9")  # a stale attempt's Closes inside the listed file
        started = time.monotonic()
        woke = self.wake_returns([{"path": str(path), "attempt": "9.2"}], max_seconds=1, slice_seconds=0.3)
        self.assertEqual(woke["reason"], "deadline")
        self.assertEqual(woke["changes"], {"panes": [], "returns": []})
        self.assertFalse(woke["journaled"])
        self.assertTrue(1 <= time.monotonic() - started < 8)
        self.close(path, "9.2")
        self.assertEqual(self.wake_returns([{"path": str(path), "attempt": "9.2"}])["reason"], "new_return")

    def test_returns_mode_refuses_a_malformed_list_before_any_socket_call(self):
        path = self.brief_file()
        good = {"path": str(path), "attempt": "9.2"}
        calls = len(self.peer.requests)
        bad = [
            "tasks/9.md", [], [good] * 33, [7], [{"path": str(path)}], [{"attempt": "9.2"}],
            [{**good, "extra": 1}], [{"path": "relative/9.md", "attempt": "9.2"}],
            [{"path": str(self.project / "missing.md"), "attempt": "9.2"}],
            [{"path": str(self.project), "attempt": "9.2"}], [{"path": str(path), "attempt": 9.2}],
            [{"path": str(path), "attempt": "9.2.1"}], [{"path": str(path), "attempt": ""}],
            [{"path": "", "attempt": "9.2"}],
        ]
        for returns in bad:
            with self.subTest(returns=returns):
                self.assertEqual(self.wake_returns(returns, expected=1)["error"]["code"], "schema_invalid")
        both = run_wake(self, {"record_root": str(self.root), "returns": [good], "max_seconds": 5}, expected=1)
        self.assertEqual(both["error"]["code"], "schema_invalid")
        neither = run_wake(self, {"max_seconds": 5}, expected=1)
        self.assertEqual(neither["error"]["code"], "schema_invalid")
        self.assertEqual(self.wake_returns([good], max_seconds=0, expected=1)["error"]["code"], "schema_invalid")
        self.assertEqual(len(self.peer.requests), calls)
        self.assertEqual(self.wake_returns([good] * 32, max_seconds=1, slice_seconds=0.3)["reason"], "deadline",
                         "control: a well-formed list of the most allowed items is accepted")
        self.init()
        self.turn()
        calls = len(self.peer.requests)
        mixed = run_wake(self, {"record_root": str(self.root), "workspace_id": "scratch", "max_seconds": 5}, expected=1)
        self.assertEqual(mixed["error"]["code"], "schema_invalid", "workspace_id belongs to returns mode")
        self.assertEqual(len(self.peer.requests), calls)

    def test_returns_mode_refuses_a_file_whose_frontmatter_names_another_attempt(self):
        path = self.brief_file("9.2.md", "9.2")
        calls = len(self.peer.requests)
        refused = self.wake_returns([{"path": str(path), "attempt": "9.3"}], expected=1)
        self.assertEqual(refused["error"]["code"], "receipt_mismatch")
        bare = self.project / "bare.md"
        bare.write_text("# no frontmatter\n\n## Return — attempt 9.2\n\nCloses: 9.2\n")
        self.assertEqual(self.wake_returns([{"path": str(bare), "attempt": "9.2"}], expected=1)["error"]["code"],
                         "receipt_mismatch")
        first = self.project / "9.md"
        first.write_text("---\ntask: 9\nowner: kai\nlatitude: own\nkind: build\nreturn: x\n---\n# Brief\n")
        self.close(first, "9")
        self.assertEqual(self.wake_returns([{"path": str(first), "attempt": "9"}])["reason"], "new_return",
                         "with no attempt field the task field names the attempt")
        self.assertEqual(len(self.peer.requests), calls)

    def test_returns_mode_with_a_workspace_also_reports_pane_changes_and_never_sends_or_reads(self):
        path = self.brief_file()
        self.move_pane_after_the_first_look()
        calls = len(self.peer.requests)
        woke = self.wake_returns([{"path": str(path), "attempt": "9.2"}], max_seconds=30, slice_seconds=0.3,
                                 workspace_id="scratch")
        self.assertEqual(woke["reason"], "pane_status", woke)
        change = woke["changes"]["panes"][0]
        self.assertEqual((change["pane_id"], change["member"], change["after"]["agent_status"]),
                         ("scratch:p1", "scratch:p1", "working"))
        self.assertEqual(woke["changes"]["returns"], [])
        self.assertFalse(woke["journaled"])
        methods = {r["method"] for r in self.peer.requests[calls:]}
        self.assertTrue(methods and not methods & SEND_OR_READ, methods)
        self.assertFalse(self.root.exists())

    def test_returns_mode_with_a_workspace_still_wakes_on_a_receipt_during_the_watch(self):
        path = self.brief_file()
        timer = threading.Timer(0.5, self.close, (path, "9.2"))
        timer.start()
        self.addCleanup(timer.join)
        woke = self.wake_returns([{"path": str(path), "attempt": "9.2"}], max_seconds=30, slice_seconds=0.3,
                                 workspace_id="scratch")
        self.assertEqual(woke["reason"], "new_return", woke)
        self.assertEqual(woke["changes"]["panes"], [])


if __name__ == "__main__":
    unittest.main()
