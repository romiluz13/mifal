#!/usr/bin/env python3
"""Budgeted M1 reconciliation. One durable first action, then return to the lead."""

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import sys
import tempfile
import time

import lead
from adapter import Client, Parser, Refusal, identifier, invalid, json_loads, object_fields, observe


IDENTITY = ("pane_id", "workspace_id", "tab_id", "terminal_id", "cwd", "agent", "name")
DEFAULTS = {"deadline_seconds": 5, "max_tasks": 32, "max_pane_reads": 8,
            "max_disk_reads": 128, "max_bytes": 8 * 1024 * 1024}
FILE_LIMIT = 2 * 1024 * 1024


@contextmanager
def deadline(seconds):
    # Socket timeouts alone are per read: a trickling peer must not extend M1.
    def expired(signum, frame):
        raise Refusal("resume_budget", "reconciliation deadline reached")
    previous = signal.signal(signal.SIGALRM, expired)
    old_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if old_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, *old_timer)


class Budget:
    def __init__(self, params):
        self.limits = {key: params.get(key, value) for key, value in DEFAULTS.items()}
        for key, value in self.limits.items():
            maximum = 60 if key == "deadline_seconds" else DEFAULTS[key] * 4
            if (type(value) not in (int, float) or not math.isfinite(value) or
                    value <= 0 or value > maximum or
                    (key != "deadline_seconds" and type(value) is not int)):
                invalid(key + " outside the finite positive budget")
        self.started = time.monotonic()
        self.used = {"tasks": 0, "pane_reads": 0, "disk_reads": 0, "bytes": 0}

    def take(self, name, count=1):
        self.check()
        if self.used[name] + count > self.limits["max_" + name]:
            raise Refusal("resume_budget", name + " cap reached")
        self.used[name] += count

    def check(self):
        if time.monotonic() - self.started >= self.limits["deadline_seconds"]:
            raise Refusal("resume_budget", "reconciliation deadline reached")

    def read(self, path):
        self.take("disk_reads")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > FILE_LIMIT:
                raise Refusal("resume_budget", "not a bounded regular file: " + str(path))
            data = stream.read(min(FILE_LIMIT, self.limits["max_bytes"] - self.used["bytes"]) + 1)
        if len(data) > FILE_LIMIT:
            raise Refusal("resume_budget", "file grew beyond read cap")
        self.take("bytes", len(data))
        return data

    def read_text(self, path):
        data = self.read(path)
        if data is None:
            raise FileNotFoundError(str(path))
        return data.decode()

    def digest(self, path):
        data = self.read(path)
        if data is None:
            raise FileNotFoundError(str(path))
        return hashlib.sha256(data).hexdigest()

    def report(self):
        return {"limits": self.limits, "used": self.used,
                "elapsed_seconds": time.monotonic() - self.started}


def verified_identity(picture, member, pins=()):
    pane_id = member["pane_id"]
    agents = [p for p in picture["members"] if p.get("pane_id") == pane_id]
    panes = [p for p in picture["panes"] if p.get("pane_id") == pane_id]
    if len(agents) != 1 or len(panes) != 1:
        raise Refusal("identity_mismatch", "member is absent or not unique")
    live = agents[0]
    identity = {key: live.get(key) for key in IDENTITY}
    for key in IDENTITY:
        if key != "name" and (not isinstance(identity[key], str) or not identity[key]):
            raise Refusal("identity_mismatch", "incomplete live identity: " + key)
        if key != "name" and panes[0].get(key) != identity[key]:
            raise Refusal("identity_mismatch", "pane and agent identity disagree: " + key)
    if identity["agent"] != member["input_box"]["agent"]:
        raise Refusal("identity_mismatch", "agent kind changed")
    for pin in pins:
        if not isinstance(pin, dict) or any(key not in pin or pin[key] != identity[key] for key in IDENTITY):
            raise Refusal("identity_mismatch", "pane id now belongs to a different member")
        seq = pin.get("state_change_seq")
        if seq is not None and (type(live.get("state_change_seq")) is not int or
                                live["state_change_seq"] < seq):
            raise Refusal("identity_mismatch", "state sequence regressed; possible server restart")
    return identity, live


class InspectionClient(Client):
    """Bound pane wire bytes before allocation/decoding, not after text arrives."""

    def __init__(self, options, budget):
        super().__init__(options)
        self.budget = budget

    def request(self, method, params):
        if method != "pane.read":
            return super().request(method, params)
        self.budget.check()
        limit = min(16 * 1024 * 1024,
                    self.budget.limits["max_bytes"] - self.budget.used["bytes"])
        if limit <= 0:
            raise Refusal("resume_budget", "pane response byte cap reached")
        try:
            # Round 3 (R-4): one deadline spans connect, send and the bounded read
            # loop, matching the core Client's whole-request bound.
            deadline = time.monotonic() + self.timeout
            connection, request_id = self.open_request(method, params, deadline)
            data = bytearray()
            with connection:
                while len(data) <= limit and b"\n" not in data:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise Refusal("transport_error",
                                      "request exceeded the total request deadline")
                    connection.settimeout(remaining)
                    chunk = connection.recv(min(65536, limit + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
            self.budget.take("bytes", min(len(data), limit))
            if len(data) > limit:
                raise Refusal("resume_budget", "pane response byte cap reached")
            if not data.endswith(b"\n"):
                raise Refusal("transport_error", "missing NDJSON response")
            response = json_loads(data)
            if not isinstance(response, dict) or response.get("id") != request_id:
                raise Refusal("transport_error", "response id mismatch")
            if "error" in response:
                raise Refusal("server_error", "herdr refused the request", server_error=response["error"])
            if not isinstance(response.get("result"), dict):
                raise Refusal("transport_error", "response has no result object")
            return response["result"]
        except (OSError, ValueError) as error:
            raise Refusal("transport_error", str(error)) from error


def dispatch_record(options, state, task, budget):
    did = state["namespace"] + "-" + task["active"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", did):
        invalid("invalid durable dispatch id")
    base = Path(options.state_dir).expanduser().resolve()
    directory = lead.local_path(base, "dispatches/" + did)
    raw = budget.read(lead.local_path(base, "dispatches/" + did + "/record.json"))
    if raw is None:
        if directory.exists():
            raise Refusal("dispatch_incomplete", "dispatch id reserved without a readable record")
        return None
    record = json_loads(raw)
    if (not isinstance(record, dict) or record.get("dispatch_id") != did or
            record.get("pane_id") != state["members"][task["owner"]]["pane_id"] or
            record.get("workspace_id") != state["workspace_id"] or
            record.get("status") not in {"prepared", "sent", "refused", "uncertain"} or
            record.get("delivery") != "unverified"):
        raise Refusal("dispatch_incomplete", "dispatch record inconsistent with the task")
    guard = record.get("guard")
    if (not isinstance(guard, dict) or not isinstance(guard.get("identity"), dict) or
            type(guard["identity"].get("state_change_seq")) is not int):
        raise Refusal("dispatch_incomplete", "dispatch record has no valid identity/sequence pin")
    return record


def receipt_check(root, task, data, budget):
    """Reuse the lead checker on bounded immutable copies; never trust a screen."""
    with tempfile.TemporaryDirectory(prefix="resume-check-") as temporary:
        copy_root = Path(temporary).resolve()
        copy = lead.local_path(copy_root, task["return"])
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(data)
        for check in task["claims"].values():
            if "path" not in check:
                continue
            source = lead.local_path(root, check["path"])
            content = budget.read(source)
            if content is not None:
                copy = lead.local_path(copy_root, check["path"])
                copy.parent.mkdir(parents=True, exist_ok=True)
                copy.write_bytes(content)
        budget.check()
        return lead.review_receipt(copy_root, task, {"artifact": task["return"]},
                                  contract_read_text=budget.read_text,
                                  contract_body_digest=budget.digest,
                                  contract_path=lead.local_path(root, task["return"]),
                                  run_checks=False)


def inspect_task(client, root, state, task, options, budget, picture, screens):
    row = {"task": task["id"], "attempt": task["active"], "classification": "ambiguous",
           "trigger": "hold", "reason": "not yet inspected"}
    record = dispatch_record(options, state, task, budget)
    member = state["members"][task["owner"]]
    pins = [member["identity"]] if "identity" in member else []
    if record:
        pins.append(record["guard"]["identity"])
        row["dispatch_status"] = record["status"]
    if not pins and task["status"] != "queued":
        raise Refusal("identity_mismatch", "in-flight task has no historical identity")
    identity, live = verified_identity(picture, member, pins)
    if identity["workspace_id"] != state["workspace_id"]:
        raise Refusal("identity_mismatch", "member left the mission workspace")
    row["identity"] = identity
    member["identity"], member["status"] = identity, live.get("agent_status")
    data = budget.read(lead.local_path(root, task["return"]))
    text = data.decode() if data is not None else ""
    closes = lead.contracts.CLOSES_LINE_RE.findall(text)
    if task["active"] in closes:
        errors, checks = receipt_check(root, task, data, budget)
        row.update(classification="completed-and-reported" if task["status"] == "accepted"
                   else "completed-unreported", reason="durable receipt and sidecars checked",
                   checks=checks, receipt_sha256=hashlib.sha256(data).hexdigest())
        if errors:
            row.update(reason="; ".join(errors))
        elif task["status"] in {"held", "refused", "review-refused", "stopped"}:
            row["reason"] = "receipt does not override the team's explicit " + task["status"] + " decision"
        else:
            row["trigger"] = "none" if task["status"] == "accepted" else "accept"
        return row
    if task["status"] == "accepted":
        row["reason"] = "accepted team record has no current closing receipt"
        return row
    pane = member["pane_id"]
    if pane not in screens:
        budget.take("pane_reads")
        read = client.request("pane.read", {
            "pane_id": pane, "source": "visible", "format": "text", "strip_ansi": True,
        }).get("read", {})
        if read.get("pane_id") != pane or read.get("truncated") is not False or not isinstance(read.get("text"), str):
            raise Refusal("output_unreadable", "bounded visible output unavailable")
        screens[pane] = read["text"]
    rings = [ring for ring in state["pending"]
             if ring["member"] == task["owner"] and
             (ring["attempt"] or ring["task"]) == task["active"]]
    for _, ring in lead.pane_rings(screens[pane], member["input_box"]["start"]):
        if (ring["attempt"] or ring["task"]) == task["active"]:
            rings.append(ring)
    row["pane_inspected"] = True
    observed = task.get("delivery_observed", {})
    if not isinstance(observed, dict):
        raise Refusal("invalid_evidence", "invalid delivery memory")
    memory = observed.get(task["active"])
    if task["active"] in observed and (not isinstance(memory, dict) or
                                      memory.get("kind") not in {"DONE", "HELP", "HELD", "STOPPED"}):
        raise Refusal("invalid_evidence", "invalid attempt delivery marker")
    if rings:
        kind = "DONE" if any(r["type"] == "DONE" for r in rings) else rings[0]["type"]
        if not memory or (kind == "DONE" and memory["kind"] != "DONE"):
            memory = {"kind": kind, "at": lead.stamp()}
            task.setdefault("delivery_observed", {})[task["active"]] = memory
            # A new resume id and a cleared viewport must never erase delivery evidence.
            lead.write_json(root, "lead-state.json", state)
    if memory and memory["kind"] == "DONE":
        row.update(classification="completed-unreported",
                   reason="current or remembered DONE lacks a validated durable receipt; never resend")
        return row
    sidecars = [check["path"] for check in task["claims"].values()
                if "path" in check and budget.read(lead.local_path(root, check["path"])) is not None]
    if record or task["status"] in {"sent", "dispatching", "uncertain", "help-answered"} or memory:
        row.update(classification="sent-unverified",
                   reason="one member inspection completed; delivery unresolved, never retry")
    elif sidecars or text:
        row["reason"] = "unclosed task artifact exists; absence of a return is not non-delivery"
    elif task["status"] == "queued" and live.get("agent_status") in {"idle", "done"}:
        row.update(classification="never-sent", trigger="dispatch",
                   reason="queued, no dispatch reservation/return/sidecar/ring; member inspected")
    else:
        row["reason"] = "member busy or task explicitly held/stopped/refused"
    return row


def persist(root, state, session):
    lead.record(root, state)
    lead.write_json(root, f"resumes/{session['id']}.json", session)
    # This additive projection leaves lead.py's normal turn surface unchanged.
    path = lead.local_path(root, "state.md")
    text = path.read_text()
    marker = "## First resume action\n"
    text = text.rsplit(marker, 1)[0] + marker + (
        f"Resume {session['id']}: {json.dumps(session['first_action'], sort_keys=True)}\n"
        f"Status: {session['status']}. Next: {session['next_step']}.\n"
        f"Evidence: resumes/{session['id']}.json\n")
    lead.write(root, "state.md", text)


def apply_first(root, state, session, options, budget):
    action = session["first_action"]
    if action["kind"] == "dispatch":
        task = state["tasks"][action["task"]]
        client = Client(options)
        # Action has its own bound; M1 inspection does not pay a 60-second idle wait.
        with deadline(90):
            entry = lead.send_task(client, root, state, task, options)
    elif action["kind"] == "human-answer":
        escalation = next(e for e in state["escalations"] if e["id"] == action["escalation"])
        with deadline(max(0.000001, budget.limits["deadline_seconds"] -
                          (time.monotonic() - budget.started))):
            budget.take("tasks", len(escalation["tasks"]))
            entry = lead.human_turn(root, state, escalation, read_text=budget.read_text)
    elif action["kind"] == "accept":
        task = state["tasks"][action["task"]]
        proof = f"reviews/{task['active']}.json"
        row = next(r for r in session["plan"] if r["task"] == task["id"])
        # Ticket 10: acceptance anchors to the artifact as it exists now, never to
        # inspection-time digests. A return that changed after inspection holds for
        # a fresh resume id; it is never accepted on stale evidence.
        path = lead.local_path(root, task["return"])
        # Round 3 (S-3): hash and review the same bytes. A member write between a
        # separate hash and a rereading review could make the proof digest describe
        # bytes the review never saw.
        if lead.matt_task(task):
            # Acceptance starts a fresh bounded recheck; inspection-time size and
            # read limits cannot protect files a worker changed in between.
            action_budget = Budget(budget.limits)
            try:
                with deadline(action_budget.limits["deadline_seconds"]):
                    receipt_bytes = action_budget.read(path)
                    if receipt_bytes is None:
                        raise Refusal("artifact_changed", "return disappeared after inspection")
                    digest = hashlib.sha256(receipt_bytes).hexdigest()
                    if digest != row["receipt_sha256"]:
                        raise Refusal("artifact_changed",
                                      "return changed after inspection; never accept stale evidence")
                    errors, evidence = receipt_check(root, task, receipt_bytes, action_budget)
            finally:
                session["action_budget"] = action_budget.report()
        else:
            receipt_bytes = Budget(budget.limits).read(path)
            if receipt_bytes is None:
                raise Refusal("artifact_changed", "return disappeared after inspection")
            digest = hashlib.sha256(receipt_bytes).hexdigest()
            if digest != row["receipt_sha256"]:
                raise Refusal("artifact_changed",
                              "return changed after inspection; never accept stale evidence")
            errors, evidence = lead.review_receipt(root, task, {"artifact": task["return"]},
                                                   text=receipt_bytes.decode())
        if not errors:
            # Trusted verifiers run outside the bounded recheck, under their own timeouts;
            # inspection never executes them.
            lead.run_deferred(task, errors, evidence)
        if errors:
            raise Refusal("claims_failed_recheck", "claims failed the acceptance-time recheck")
        lead.write_json(root, proof, {"attempt": task["active"], "receipt": task["return"],
                                     "errors": [], "checks": evidence, "at": lead.stamp(),
                                     "receipt_sha256": digest})
        task.update(status="accepted", accepted_evidence=proof)
        entry = {"action": "accept", "task": task["active"], "evidence": proof}
    else:
        entry = {"action": action["kind"], "reason": action["reason"]}
    return entry


def release_latch(root):
    (root / ".resume-latch").unlink()
    fd = os.open(root, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def resume(params, options):
    object_fields(params, {"record_root", "resume_id", *DEFAULTS}, {"record_root", "resume_id"})
    root = Path(identifier(params["record_root"], "record_root"))
    if not root.is_absolute():
        invalid("record_root must be absolute")
    root = root.resolve()
    rid = params["resume_id"]
    if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", rid):
        invalid("resume_id must be a stable path-safe token")
    budget = Budget(params)
    with lead.record_lock(root):
        was_latched = lead.resume_latched(root)
        if not was_latched:
            lead.write(root, ".resume-latch", rid + "\n")
        # A corrupt index refuses with the fresh latch kept: its evidence is unknown, so nothing may dispatch.
        state = lead.load_state(budget.read(lead.local_path(root, "lead-state.json")))
        if state.get("outcome", {}).get("status") == "failed":
            # Same terminal rule as a lead turn: no reconciliation can reopen a failed mission.
            if not was_latched:
                release_latch(root)
            raise Refusal("mission_failed",
                          "mission reached a durable failure; inspect " + state["outcome"]["evidence"])
        previous = budget.read(lead.local_path(root, f"resumes/{rid}.json"))
        if previous is not None:
            session = json_loads(previous)
            if state.get("resume_gate", {}).get("id") != rid:
                return {**session, "replayed": True, "handoff": "hold",
                        "next_step": "use the current resume_gate, not this superseded session"}
            if session["status"] != "finished":
                # Prepared/started actions may already have reached the member.
                # Do not replay them: a new reconciliation can discover receipts.
                session.update(status="finished", handoff="hold",
                               outcome={"action": "hold", "reason": "interrupted first action; never replay"},
                               next_step="inspect new evidence with a new resume_id; never retry this action")
                state["resume_gate"] = {"id": rid, "status": "hold"}
                persist(root, state, session)
            if (session["handoff"] == "lead" and not was_latched and
                    state["resume_gate"]["status"] == "ready"):
                release_latch(root)
            elif session["handoff"] == "lead":
                return {**session, "replayed": True, "handoff": "hold",
                        "next_step": "a latch survived; use a new resume_id for fresh inspection"}
            return {**session, "replayed": True}
        session = {"id": rid, "status": "inspecting", "plan": [], "handoff": "hold",
                   "first_action": {"kind": "hold", "reason": "inspection interrupted"},
                   "next_step": "repeat this resume_id to recover the single first action"}
        state["resume_gate"] = {"id": rid, "status": "hold"}
        persist(root, state, session)
        picture, screens, failure = None, {}, None
        waiting = next((e for e in state["escalations"] if e["status"] == "waiting"), None)
        try:
            with deadline(max(0.000001, budget.limits["deadline_seconds"] -
                              (time.monotonic() - budget.started))):
                if not waiting:
                    client = InspectionClient(options, budget)
                    client.timeout = min(2, budget.limits["deadline_seconds"])
                    # Never reuse last_watch: events are invalidations, not current identity.
                    picture = observe(client, {"workspace_id": state["workspace_id"]})
                for task in (() if waiting else state["tasks"].values()):
                    budget.take("tasks")
                    try:
                        row = inspect_task(client, root, state, task, options, budget, picture, screens)
                    except (Refusal, OSError, ValueError, KeyError, TypeError) as error:
                        if getattr(error, "code", None) == "resume_budget":
                            raise
                        row = {"task": task["id"], "attempt": task["active"],
                               "classification": "ambiguous", "trigger": "hold",
                               "reason": str(error), "code": getattr(error, "code", "invalid_evidence"),
                               "refused_actions": ["prompt", "close"]}
                    session["plan"].append(row)
        except (Refusal, OSError, ValueError, KeyError, TypeError) as error:
            failure = {"code": getattr(error, "code", "invalid_evidence"), "reason": str(error)}
        # Git evidence runs after the inspection deadline so it can never decide a trigger.
        git_started = time.monotonic()
        for row in session["plan"]:
            task = state["tasks"][row["task"]]
            if task.get("git_base", {}).get(task["active"]):
                row["git"] = (lead.git_window(state, task)
                              if time.monotonic() - git_started < 2 * lead.GIT_TIMEOUT
                              else "unavailable: resume git evidence budget spent")
        session["budget"] = budget.report()
        session["inspection_error"] = failure
        session["uninspected_tasks"] = len(state["tasks"]) - len(session["plan"])
        holds = [row for row in session["plan"] if row["trigger"] == "hold"]
        accepts = [row for row in session["plan"] if row["trigger"] == "accept"]
        assignments = [row for row in session["plan"] if row["trigger"] == "dispatch" and
                       all(lead.satisfied(state, dep) for dep in state["tasks"][row["task"]].get("after", []))]
        if waiting and not failure:
            action = {"kind": "human-answer", "escalation": waiting["id"]}
        elif failure or holds:
            action = {"kind": "hold", "reason": "bounded reconcile needs evidence or human decision"}
        elif accepts:
            action = {"kind": "accept", "task": accepts[0]["task"]}
        elif assignments:
            row = max(assignments, key=lambda r: state["tasks"][r["task"]]["value"])
            action = {"kind": "dispatch", "task": row["task"], "identity": row["identity"]}
        else:
            action = {"kind": "handoff", "reason": "no unresolved evidence; continue the lead loop"}
        session.update(status="started", first_action=action)
        persist(root, state, session)  # WAL before the first effect, including pane input.
        try:
            session["outcome"] = apply_first(root, state, session, options, budget)
        except (Refusal, OSError, ValueError) as error:
            session["outcome"] = {"action": "hold", "reason": str(error),
                                  "code": getattr(error, "code", "action_failed")}
        if action["kind"] == "human-answer":
            session["budget"] = budget.report()
        pending_accepts = len(accepts) > (1 if action["kind"] == "accept" else 0)
        handoff = (session["outcome"]["action"] in {"accept", "dispatch", "handoff"}
                   and not pending_accepts)
        session.update(status="finished", handoff="lead" if handoff else "hold",
                       next_step="run one lead turn" if handoff else
                       "inspect new evidence with a new resume_id; do not resend reserved dispatch ids")
        state["resume_gate"] = {"id": rid, "status": "ready" if handoff else "hold"}
        state["progress"].append({"at": lead.stamp(), "moment": "M1", "action": "resume",
                                  "reason": session["next_step"], "evidence": f"resumes/{rid}.json",
                                  "first_action": action, "outcome": session["outcome"]})
        persist(root, state, session)
        if handoff:
            release_latch(root)
        return {**session, "replayed": False}


def handle(payload, options):
    object_fields(payload, {"command", "params"}, {"command", "params"})
    if payload["command"] != "resume":
        raise Refusal("unknown_command", "expected resume; no close or raw prompt operation exists")
    return resume(payload["params"], options)


def main():
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("--socket", default=os.environ.get(
            "HERDR_SOCKET_PATH", os.path.expanduser("~/.config/herdr/herdr.sock")))
        parser.add_argument("--state-dir", default=os.path.expanduser("~/.local/state/herdr-adapter"))
        parser.add_argument("--idle-seconds", type=float, default=60)
        parser.add_argument("--read-gap-seconds", type=float, default=10)
        parser.add_argument("--shell-ready-ms", type=float, default=500)
        options = parser.parse_args()
        if (any(not math.isfinite(getattr(options, key)) or not 0 < getattr(options, key) <= 60
                for key in ("idle_seconds", "read_gap_seconds")) or
                not 500 <= options.shell_ready_ms <= 2500):
            invalid("invalid bounded guard timings")
        result = handle(json_loads(sys.stdin.read()), options)
        print(json.dumps({"ok": True, "result": result}, allow_nan=False))
        return 0
    except (Refusal, OSError, ValueError, KeyError, TypeError, lead.compliance.UsageError) as error:
        print(json.dumps({"ok": False, "error": {
            "code": getattr(error, "code", "invalid_input"), "message": str(error),
        }}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
