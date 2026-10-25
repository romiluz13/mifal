#!/usr/bin/env python3
"""One lead turn, not a daemon. JSON in/out; see LEAD.md for the trusted plan seam."""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

from adapter import (Client, Parser, Refusal, dispatch, durable_write, identifier,
                     invalid, json_loads, object_fields, observe)
from event_loop import watch


SCRIPTS = Path(__file__).resolve().parents[2] / "skills/team-lead/scripts"


def load_contract_module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contracts = load_contract_module("validate_contracts")
compliance = load_contract_module("check_compliance")
PRIORITY = {"HELP": 300, "HELD": 300, "STOPPED": 300, "DONE": 200, "assign": 100}
MATT_CONTEXT = {"route": "Route", "next_gate": "Next gate", "start": "Start",
                "ddd": "DDD", "ux": "UX", "state": "State"}
# Same per-file and total ceilings as resume's bounded reader.
PROCEDURE_LIMIT = 2 * 1024 * 1024
DELIVERY_LIMIT = 8 * 1024 * 1024
IDLE_REVIEW_TURNS = 3
VERIFIER_LIMIT = 600
GIT_TIMEOUT = 5
UNKNOWN = "UNKNOWN"
IN_FLIGHT = ("dispatching", "sent", "uncertain", "help-answered", "review-pending")
# One row per agent_status in api-schema.json (AgentStatus): what an owner row says about an in-flight owner with no
# closing return, and the blind spot it names. working is the only status that is not silence.
LOOK_AT_PANE = "look at the pane"
OWNER_ROWS = {
    "idle": ("is idle", "a /clear or replaced session in the pane looks the same"),
    "done": ("is done", "a /clear or replaced session in the pane looks the same"),
    "blocked": ("is blocked", "the pane waits on a dialog only a human answers: look at it, never type into it"),
    "unknown": ("has Herdr status unknown", "Herdr cannot tell what the pane is doing: " + LOOK_AT_PANE),
    "working": None,
}
IDENTITY_KINDS = ("reviewed", "installed", "bounded")
ATTENTION_MINUTES = 10
MAX_PINS = 64
MAX_PIN_BYTES = 512 * 1024 * 1024  # a verifier file larger than this cannot be pinned, so its plan is refused
PANE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_.-]{0,63}")
ATTEMPT_RE = re.compile(r"[0-9]+(\.[0-9]+)?")
PIN_FIELDS = {"return", "attempt", "matt", "dispatched_at"}
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def matt_task(task):
    return task.get("workflow", {}).get("methodology", "").strip().lower() in {
        "matt", "ask-matt", "matt-pocock"}


def cut_lines(workflow):
    return [workflow["cut"]] if isinstance(workflow["cut"], str) else workflow["cut"]


def single_line(value, label):
    """A value the brief writes as one Workflow line; a second line would forge another key."""
    identifier(value, label)
    if len(value.splitlines()) != 1 or "\0" in value:
        invalid(label + " must be a single line")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def local_path(root, value):
    identifier(value, "record path")
    path = (root / value).resolve()
    if path == root or root not in path.parents:
        raise Refusal("path_outside_record", "artifact must stay inside record root")
    return path


def write(root, name, text):
    path = local_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    durable_write(path, text)
    return path


def write_json(root, name, value):
    return write(root, name, json.dumps(value, indent=2, allow_nan=False) + "\n")


def checked(kind, text, path=None, matt=False, read_text=None, body_digest=None):
    errors = getattr(contracts, "validate_" + kind)(text, kind)
    if matt:
        if kind == "receipt":
            errors += contracts.validate_brief(text, str(path))
        errors += contracts.validate_workflow(text, path, require_loads=kind == "receipt",
                                             receipt=kind == "receipt", read_text=read_text,
                                             body_digest=body_digest)
    if errors:
        raise Refusal("contract_invalid", "; ".join(errors))
    return text


@contextmanager
def record_lock(root):
    with local_path(root, ".lead.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Refusal("lead_in_progress", "one writer per team record") from error
        yield


def parse_stamp(value):
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else None


def span(seconds):
    seconds = int(seconds)
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"


def cell(value):
    return str(value).replace("|", "/").replace("\n", " ").strip() or UNKNOWN


def read_json(root, relative):
    """A bounded JSON read for the projection; anything unreadable is None, never a guess."""
    try:
        return json.loads(BoundedReader(max_reads=1).text(local_path(root, relative)))
    except (OSError, UnicodeError, ValueError, Refusal):
        return None


def busy_with(state, owner):
    """Attempts this owner holds that are neither queued nor finished."""
    return [t["active"] for t in state["tasks"].values() if t["owner"] == owner and t["status"] not in
            {"accepted", "queued", "refused", "stopped", "review-refused"}]


def latest_identities(task):
    """The identity shown per kind: the latest one recorded for the active attempt."""
    latest = {}
    for row in task.get("identities", []):
        if row.get("attempt") == task["active"]:
            latest[row.get("kind")] = row
    return latest


def satisfied(state, dep):
    """A predecessor releases its dependents only when accepted at full scope: a recorded bounded scope never does."""
    task = state["tasks"][dep]
    return task["status"] == "accepted" and "bounded" not in latest_identities(task)


def assignable(state, task):
    """The one rule for an idle owner taking a queued task; pick(), the attention rows and the next-action column share it."""
    member = state["members"][task["owner"]]
    ready = all(satisfied(state, dep) for dep in task.get("after", []))
    return (task["status"] == "queued" and member.get("status") in {"idle", "done"} and
            not busy_with(state, task["owner"]) and ready)


def claimed_revisions(root, task):
    """Digests the receipt names in its Claims section; nothing else counts as a claimed revision."""
    try:
        text = BoundedReader(max_reads=1).text(local_path(root, task["return"]))
        suffix = receipt_suffix(task, text)
        portions = [p for _, p in contracts.split_returns(suffix)
                    if contracts.CLOSES_LINE_RE.findall(p) == [task["active"]]]
        claims = contracts.find_section(contracts.sections(portions[-1], 3), "Claims") if portions else ""
    except (OSError, UnicodeError, ValueError, KeyError, Refusal):
        return []
    found = re.findall(r"\b[0-9a-f]{64}\b|\b[0-9a-f]{40}\b", claims or "")
    return list(dict.fromkeys(found))[:3]


def attempts_of(state, task):
    """The attempts that exist: the first, the active one, and each correction the lead created. A progress entry
    that merely names an attempt (a rejected doorbell, a recorded identity) does not create one."""
    ids = {task["id"], task["active"]} | {e["next_attempt"] for e in state["progress"]
                                         if e.get("action") == "correct" and isinstance(e.get("next_attempt"), str) and
                                         re.fullmatch(re.escape(task["id"]) + r"\.[0-9]+", e["next_attempt"])}
    return sorted(ids, key=lambda a: [int(n) for n in a.split(".")])


def evidence_roots(root):
    """The only places record evidence may live: the record root and its parent directory."""
    return (root, root.parent)


def resolve_evidence(root, value):
    candidate = Path(value).expanduser()
    return (candidate if candidate.is_absolute() else root / candidate).resolve()


def within(path, bases):
    return any(path == base or base in path.parents for base in bases)


def opened_path(fd):
    """Where the kernel says an open descriptor really is, so a path swapped after a containment check is seen."""
    if hasattr(fcntl, "F_GETPATH"):
        return Path(os.fsdecode(fcntl.fcntl(fd, fcntl.F_GETPATH, b"\0" * 1024).split(b"\0", 1)[0]))
    return Path(os.readlink(f"/proc/self/fd/{fd}"))


def evidence_intact(root, row):
    """True when the evidence still sits under the allowed roots with the bytes the record stored. The digest is
    read from a descriptor opened without following a final symlink and checked against the roots by its real
    path, so a swap between the containment check and the read cannot be followed."""
    try:
        resolved = resolve_evidence(root, row["evidence"])
        roots = evidence_roots(root)
        return (within(resolved, roots) and
                BoundedReader(max_reads=1, confine=roots).digest(resolved) == row.get("evidence_sha256"))
    except (KeyError, OSError, ValueError, RuntimeError):
        return False


def identity_cell(task, kind, broken=False):
    rows = [i for i in task.get("identities", []) if i.get("kind") == kind and i.get("attempt") == task["active"]]
    if not rows:
        return UNKNOWN
    last = rows[-1]
    more = f" (+{len(rows) - 1} earlier)" if len(rows) > 1 else ""
    note = " (evidence missing or changed)" if broken else ""
    return f"{last['identity'][:12]} by {last['by']}{more}{note}"


def proof_matches(proof, attempt, receipt):
    """A review proof counts only for the attempt and assigned return it names, with no recorded errors."""
    return (isinstance(proof, dict) and proof.get("errors") == [] and
            proof.get("attempt") == attempt and proof.get("receipt") == receipt)


def outcome_row(root, state, task, closing):
    raw = task["status"]
    latest = latest_identities(task)
    kinds = set(latest)
    proof = read_json(root, f"reviews/{task['active']}.json")
    held = raw in {"review-pending", "held"} or task.get("verifier_held")
    gate = None
    broken = {kind for kind, row in latest.items() if not evidence_intact(root, row)} if raw == "accepted" else set()
    if raw == "accepted":
        if not isinstance(proof, dict) or proof.get("errors") != []:
            display, gate = UNKNOWN, "review proof missing or unreadable (reviews/" + task["active"] + ".json)"
        elif not proof_matches(proof, task["active"], task["return"]):
            display, gate = UNKNOWN, (f"review proof does not match attempt {task['active']} and receipt "
                                      f"{task['return']} (reviews/{task['active']}.json)")
        elif broken:
            display, gate = UNKNOWN, "evidence missing or changed"
        elif closing.get(task["id"]):
            display, gate = "blocked-on-check", "completion check: " + "; ".join(closing[task["id"]])[:160]
        else:
            notes = []
            if "installed" in kinds:
                display = "released (bounded scope)" if "bounded" in kinds else "released"
            elif "bounded" in kinds:
                display = "accepted-bounded"
            else:
                display = "implemented"
            if "bounded" in kinds:
                notes.append("bounded scope revision recorded; not the full scope "
                             f"(excluded scope noted in {latest['bounded']['evidence']})")
            if "installed" in kinds and "reviewed" not in kinds:
                notes.append("installed without a recorded review")
            gate = "; ".join(notes) or None
    elif "installed" in kinds:
        display, gate = UNKNOWN, "installed identity recorded but the work is not accepted (contradictory)"
    elif held:
        display = "blocked-on-check"
    else:
        display = None
    status = raw if display is None else f"{display} [{raw}]"
    escalation = next((e for e in state["escalations"]
                       if e["status"] == "waiting" and task["active"] in e.get("tasks", [])), None)
    unmet = [(d, "accepted-bounded" if state["tasks"][d]["status"] == "accepted" else state["tasks"][d]["status"])
             for d in task.get("after", []) if not satisfied(state, d)]
    member_status = state["members"][task["owner"]].get("status")
    if raw == "queued":
        if unmet:
            gate = "waits on " + ", ".join(f"{d} ({s})" for d, s in unmet)
            dead = any(s in {"refused", "stopped", "review-refused"} for _, s in unmet)
            bounded = any(s == "accepted-bounded" for _, s in unmet)
            action = ("none: a predecessor ended without acceptance; a human decides" if dead
                      else "none: a predecessor is accepted-bounded; a human decides whether its scope covers this task"
                      if bounded else "none until the predecessors are accepted")
        elif assignable(state, task):
            action = "dispatch on the next lead turn"
        elif member_status is None:
            action = UNKNOWN + " (owner not observed yet)"
        elif busy_with(state, task["owner"]):
            action = f"wait for {task['owner']} to finish task " + ", ".join(busy_with(state, task["owner"]))
        else:
            action = "wait for the owner to become idle"
    elif raw in {"dispatching", "uncertain"}:
        action, gate = "run resume; never resend", gate or "delivery unverified"
    elif raw == "sent":
        action = "wait for DONE, HELP or HELD; the lead also checks the return file each turn"
    elif raw == "help-answered":
        action = "wait for the owner to continue"
    elif raw == "review-pending":
        action, gate = "owner completes the receipt; the lead reviews it again", gate or "receipt incomplete"
    elif raw == "held":
        gate = gate or ("trusted verifier unverified" if task.get("verifier_held") else
                        f"human escalation {escalation['id']} waiting" if escalation else "held")
        action = "human answer" + (f" for escalation {escalation['id']}" if escalation else "")
    elif raw == "accepted":
        action = ("none" if display.startswith("released") else
                  "restore the evidence file or record the identity again" if gate == "evidence missing or changed"
                  else "record a reviewed or installed identity")
    else:
        action, gate = "none: terminal; reconcile with a human answer or a new mission", gate or raw
    git = task.get("git_base", {}).get(task["active"])
    parts = []
    if isinstance(git, str) and git and not git.startswith("unavailable"):
        parts.append("git " + git[:12])
    revisions = claimed_revisions(root, task)
    if revisions:
        parts.append("claimed " + ", ".join(r[:12] for r in revisions))
    return [task["id"], task["owner"], task["outcome"], "; ".join(parts) or UNKNOWN,
            identity_cell(task, "reviewed", "reviewed" in broken), identity_cell(task, "installed", "installed" in broken),
            action, gate or "none", status]


def attempt_rows(root, state, task):
    rows = []
    for attempt in attempts_of(state, task):
        dispatched = next((e["at"] for e in state["progress"]
                           if e.get("action") == "dispatch" and e.get("task") == attempt), None)
        returned = task.get("returned_at", {}).get(attempt)
        proof = read_json(root, f"reviews/{attempt}.json")
        assigned = task["return"] if attempt == task["active"] else f"tasks/{attempt}.md"
        accepted = proof.get("at") if proof_matches(proof, attempt, assigned) else None
        r, a = parse_stamp(returned), parse_stamp(accepted)
        review = span((a - r).total_seconds()) if r and a and a >= r else UNKNOWN
        rounds = int(attempt.split(".")[1]) - 1 if "." in attempt else 0
        asked = sum(1 for e in state["escalations"] if e["status"] == "answered" and attempt in e.get("tasks", []))
        rows.append([attempt, dispatched or UNKNOWN, returned or UNKNOWN, accepted or UNKNOWN,
                     review, str(rounds), str(asked)])
    return rows


def attention_limit(task=None):
    """Minutes a dispatched attempt may sit before the lead is told: the task's own setting, else the default."""
    configured = (task or {}).get("workflow", {}).get("attention_minutes")
    return configured if type(configured) in (int, float) and configured > 0 else ATTENTION_MINUTES


def without_fences(text):
    """Blank the lines of fenced code blocks (``` or ~~~, closed by a fence at least as long, or the end of the text),
    so a Markdown example of a receipt is never read as one."""
    lines, fence = [], None
    for line in text.splitlines(keepends=True):
        match = FENCE_RE.match(line)
        if fence is None:
            fence = match.group(1) if match else None
            lines.append("\n" if fence else line)
        else:
            lines.append("\n")
            if (match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence) and
                    not line.strip().strip(fence[0])):
                fence = None
    return "".join(lines)


def closing_sections(text, attempt):
    """Receipt sections of a task file that close this attempt, outside code fences. split_returns falls back to the
    whole text, with an empty label, when no heading starts a receipt; a bare Closes line there is not a return."""
    return [portion for label, portion in contracts.split_returns(without_fences(text))
            if label and attempt in contracts.CLOSES_LINE_RE.findall(portion)]


def pin_path(root, pane_id):
    if type(pane_id) is not str or not PANE_RE.fullmatch(pane_id) or ".." in pane_id:
        raise Refusal("schema_invalid", "pane_id must be a Herdr pane id")
    return local_path(root, f"assignments/{pane_id}.json")


def load_pin(root, pane_id):
    """The manual path's dispatch pin for a pane ({return, attempt, matt, dispatched_at}), None when there is no pin
    file, and Refusal pin_invalid when a pin exists but cannot be used."""
    path = pin_path(root, pane_id)
    if not path.exists():
        return None
    name = f"assignments/{pane_id}.json"
    try:
        pin = json_loads(BoundedReader(max_reads=1).text(path))
    except (OSError, UnicodeError, ValueError, Refusal) as error:
        raise Refusal("pin_invalid", f"{name} is unreadable: {error.__class__.__name__}") from error
    if (not isinstance(pin, dict) or set(pin) != PIN_FIELDS or type(pin["return"]) is not str or
            not os.path.isabs(pin["return"]) or type(pin["attempt"]) is not str or
            not ATTEMPT_RE.fullmatch(pin["attempt"]) or type(pin["matt"]) is not bool or
            parse_stamp(pin["dispatched_at"]) is None):
        raise Refusal("pin_invalid", f"{name} is malformed")
    return pin


def pin_rows(root, state, now):
    """Attention for dispatches the manual path pinned: the owner is idle or done, or not observable, and the pinned
    return does not close the pinned attempt after attention_minutes."""
    try:
        files = sorted(p.name for p in local_path(root, "assignments").iterdir() if p.name.endswith(".json"))
    except (OSError, Refusal):
        return []
    owners = {member["pane_id"]: name for name, member in state["members"].items()}
    rows = []
    for file in files[:MAX_PINS]:
        pane = file[:-len(".json")]
        try:
            pin = load_pin(root, pane)
        except Refusal:
            rows.append(f"assignment pin {file} is unreadable or malformed ({UNKNOWN}); that dispatch is not tracked")
            continue
        try:
            closed = bool(closing_sections(BoundedReader(max_reads=1).text(Path(pin["return"])), pin["attempt"]))
        except (OSError, UnicodeError, Refusal):
            closed = False
        waited = (now - parse_stamp(pin["dispatched_at"])).total_seconds()
        if closed or waited <= attention_limit() * 60:
            continue
        tail = f"has no return closing it (dispatched {span(waited)} ago, limit {attention_limit()}m)"
        owner = owners.get(pane)
        if owner is None:
            rows.append(f"assignment pin {pane} (attempt {pin['attempt']}) {tail}; "
                        f"owner status {UNKNOWN} (pane is not a member of this record)")
            continue
        status = state["members"][owner].get("status")
        if status in {"idle", "done"}:
            rows.append(f"owner {owner} is {status} while assignment pin {pane} (attempt {pin['attempt']}) {tail}")
        elif status is None:
            rows.append(f"assignment pin {pane} (attempt {pin['attempt']}) {tail}; owner status {UNKNOWN} (not observed yet)")
    return rows


def attention_rows(root, state, now):
    rows = []
    for task in state["tasks"].values():
        if assignable(state, task):
            rows.append(f"idle member {task['owner']} has eligible queued task {task['id']}; "
                        "no lead turn has dispatched it")
        returned = parse_stamp(task.get("returned_at", {}).get(task["active"]))
        limit = attention_limit(task)
        if returned and task["status"] in IN_FLIGHT and (now - returned).total_seconds() > limit * 60:
            rows.append(f"DONE {task['active']} returned {span((now - returned).total_seconds())} ago "
                        f"and is not reviewed (limit {limit}m)")
        status = state["members"][task["owner"]].get("status")
        # None is no observation yet, not a Herdr status; a value the schema does not list needs a look too.
        row = (OWNER_ROWS.get(status, (f"reports the unrecognised Herdr status {status!r}", LOOK_AT_PANE))
               if status is not None else None)
        if task["status"] in IN_FLIGHT and row and return_status(root, task) is None:
            sent = [e["at"] for e in state["progress"] if e.get("action") == "dispatch" and e.get("task") == task["active"]]
            dispatched = parse_stamp(sent[-1]) if sent else None
            waited = (now - dispatched).total_seconds() if dispatched else None
            if waited is None or waited > limit * 60:
                rows.append(f"owner {task['owner']} {row[0]} while task {task['active']} has no return closing it "
                            f"({'dispatch time ' + UNKNOWN if waited is None else 'dispatched ' + span(waited) + ' ago'}, "
                            f"limit {limit}m); {row[1]}")
        if task["status"] == "queued":
            for dep in task.get("after", []):
                if state["tasks"][dep]["status"] == "accepted" and not satisfied(state, dep):
                    rows.append(f"dependent {task['id']} held by accepted-bounded predecessor {dep}; a human decides")
    rows += pin_rows(root, state, now)
    wake, last = state.get("wake"), parse_stamp(state.get("last_turn_at"))
    for task in state["tasks"].values():
        if task["status"] not in IN_FLIGHT:
            continue
        if not wake:
            rows.append(f"task {task['active']} is in flight with no wake recorded; "
                        "nothing will start the next lead turn")
        elif last is None:
            rows.append(f"task {task['active']} is in flight and the last lead turn is {UNKNOWN}")
        elif (now - last).total_seconds() > wake["deadline_seconds"]:
            rows.append(f"task {task['active']} is in flight and the last lead turn was "
                        f"{span((now - last).total_seconds())} ago, past the {wake['deadline_seconds']}s "
                        f"wake deadline ({wake['mechanism']})")
    return rows


def parent_line(state):
    paths = [t["workflow"]["state"] for t in state["tasks"].values()
             if matt_task(t) and t["workflow"].get("state")]
    if not paths:
        return "none declared"
    try:
        text = BoundedReader(max_reads=1).text(paths[0])
    except (OSError, UnicodeError) as error:
        return f"{paths[0]}: {UNKNOWN} ({error.__class__.__name__})"
    def field(name):
        match = re.search(rf"(?mi)^{name}:\s*(.+)$", text)
        return match.group(1).strip() if match else UNKNOWN
    boxes = re.findall(r"(?m)^\s*- \[([ xX])\]", text)
    return (f"{paths[0]}; phase {field('Phase')}; next gate {field('Next gate')}; "
            f"snapshot {field('Snapshot')}; checklist {sum(b != ' ' for b in boxes)}/{len(boxes)} done")


def render_current_state(root, state, now=None):
    now = now or datetime.now(timezone.utc)
    closing = {}
    checks = read_json(root, "closing-checks.json")
    for row in checks if isinstance(checks, list) else []:
        if isinstance(row, dict) and row.get("errors") and "task" in row:
            closing[str(row["task"]).split(".")[0]] = row["errors"]
    wake, last = state.get("wake"), state.get("last_wake")
    outcome = state.get("outcome", {})
    lines = ["## Current state",
             "Generated by lead.record() from lead-state.json, reviews/ and the parent note. "
             "Do not edit; the next lead turn overwrites it.", "",
             f"- As of: {now.isoformat()}",
             f"- Mission: {state['mission']}",
             "- Outcome: " + (f"FAILED ({outcome.get('evidence', UNKNOWN)})" if outcome.get("status") == "failed"
                              else "in progress"),
             f"- Last lead turn: {state.get('last_turn_at') or UNKNOWN}",
             "- Wake: " + (f"{wake['mechanism']}; deadline {wake['deadline_seconds']}s" if wake
                          else "NONE recorded"),
             "- Last wake: " + (f"{last.get('at', UNKNOWN)} ({last.get('reason', UNKNOWN)})" if last
                               else "none recorded"),
             f"- Parent note: {parent_line(state)}", "",
             "### Lead attention needed"]
    attention = attention_rows(root, state, now)
    lines += [f"- {row}" for row in attention] or ["- none"]
    lines += ["", "### Outcomes",
              "| task | owner | scope | source identity | reviewed identity | installed identity | "
              "next permitted action | open gate | status |", "|---|---|---|---|---|---|---|---|---|"]
    ordered = sorted(state["tasks"].values(), key=lambda t: int(t["id"]))
    lines += ["| " + " | ".join(cell(c) for c in outcome_row(root, state, t, closing)) + " |" for t in ordered]
    lines += ["", "### Attempts",
              "| attempt | dispatched | returned | accepted | time in review | correction rounds | "
              "human interventions |", "|---|---|---|---|---|---|---|"]
    for task in ordered:
        lines += ["| " + " | ".join(cell(c) for c in row) + " |" for row in attempt_rows(root, state, task)]
    return "\n".join(lines) + "\n"


def record(root, state, entry=None):
    if entry:
        state["progress"].append({"at": stamp(), **entry})
    write_json(root, "lead-state.json", state)
    try:
        current = render_current_state(root, state).splitlines()
    except Exception as error:  # a derived view must never stop the durable index being written
        current = ["## Current state", f"{UNKNOWN}: projection failed: {error.__class__.__name__}: {error}"]
    rows = [
        "# Team state", ""] + current + ["", "## Mission", state["mission"],
        "Finish: every required task accepted after receipt and artifact checks.",
        "", "## Authority", "Local brief/help/review only. Human reserves models, hiring, "
        "publishing, spending, destructive operations.", "", "## Roster",
        f"- lead: {state['lead_pane_id']} (turn-based manager)",
    ]
    for name, member in state["members"].items():
        rows.append(f"- {name}: {member['pane_id']}; kind {member['input_box']['agent']}; "
                    f"session {member.get('identity', {}).get('terminal_id', 'not yet observed')}; "
                    "role mission member")
    rows += ["", "## Active work",
             "| task | owner | attempt | state | latitude | expected | return |",
             "|---|---|---|---|---|---|---|"]
    for task in state["tasks"].values():
        rows.append(f"| {task['id']} | {task['owner']} | {task['active']} | {task['status']} | "
                    f"do-tell | next bounded turn | {task['return']} |")
    rows += ["", "## Progress log"]
    rows += [f"- {e['at']} {json.dumps(e, ensure_ascii=True)}" for e in state["progress"]]
    rows += ["", "## First resume action",
             "Run one lead turn: reconcile live identities, pending doorbells and receipts "
             "before any dispatch. Never retry dispatching/uncertain work on a new id.", ""]
    write(root, "state.md", "\n".join(rows))
    decisions = ["# Decisions", "", "Decision | Why | Evidence | Challenger | Reopen", ""]
    decisions += [f"- {e.get('action')}: {e.get('reason', '')}; evidence: "
                  f"{e.get('evidence', 'state.md progress log')}; challenger: "
                  f"{e.get('member', 'lead')}; reopen: new receipt or human answer."
                  for e in state["progress"]]
    write(root, "decisions.md", "\n".join(decisions) + "\n")


def topological_order(tasks):
    """Order task ids so every dependency precedes its dependent; refuse cycles."""
    ordered, marks = [], {}
    def visit(tid):
        if marks.get(tid) == "done":
            return
        if marks.get(tid) == "active":
            invalid("task dependencies must be acyclic: task " + tid + " is in a cycle")
        marks[tid] = "active"
        for dep in tasks[tid].get("after", []):
            visit(dep)
        marks[tid] = "done"
        ordered.append(tid)
    for tid in tasks:
        visit(tid)
    return ordered


def init(params):
    required = {"record_root", "project_root", "workspace_id", "lead_pane_id", "mission", "members", "tasks"}
    object_fields(params, required | {"wake"}, required)
    root = Path(identifier(params["record_root"], "record_root"))
    project = Path(identifier(params["project_root"], "project_root"))
    if not root.is_absolute() or not project.is_absolute():
        invalid("record_root and project_root must be absolute")
    root, project = root.resolve(), project.resolve()
    identifier(params["workspace_id"], "workspace_id")
    identifier(params["lead_pane_id"], "lead_pane_id")
    identifier(params["mission"], "mission")
    if not isinstance(params["members"], list) or not isinstance(params["tasks"], list):
        invalid("members and tasks must be arrays")
    if "wake" in params:
        # The caller-side mechanism that starts the next lead turn (lead.py itself schedules nothing).
        wake = params["wake"]
        object_fields(wake, {"mechanism", "deadline_seconds"}, {"mechanism", "deadline_seconds"})
        if not isinstance(wake["mechanism"], str) or not wake["mechanism"].strip() or \
                wake["mechanism"] != wake["mechanism"].strip():
            invalid("wake mechanism must be a nonempty string")
        if (type(wake["deadline_seconds"]) not in (int, float) or not math.isfinite(wake["deadline_seconds"]) or
                not 60 <= wake["deadline_seconds"] <= 3600):
            invalid("wake deadline_seconds must be between 60 and 3600")
    members, tasks = {}, {}
    for member in params["members"]:
        object_fields(member, {"name", "pane_id", "input_box"}, {"name", "pane_id", "input_box"})
        name = member["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name) or name in members:
            invalid("member names must be unique safe names")
        identifier(member["pane_id"], "pane_id")
        object_fields(member["input_box"], {"agent", "start", "end"}, {"agent", "start", "end"})
        for value in member["input_box"].values():
            identifier(value, "input box value")
        members[name] = member
    if not members or len({m["pane_id"] for m in members.values()}) != len(members):
        invalid("members must have unique explicit panes")
    if params["lead_pane_id"] in {m["pane_id"] for m in members.values()}:
        invalid("lead must live in its own pane")
    for supplied in params["tasks"]:
        required_task = {"id", "owner", "why", "outcome", "value", "claims", "stop_rule",
                         "planned_commands", "files_changed"}
        object_fields(supplied, required_task | {"help_answers", "requests", "required", "after",
                                                 "kind", "workflow"},
                      required_task)
        tid = supplied["id"]
        if not isinstance(tid, str) or not re.fullmatch(r"[0-9]+", tid) or tid in tasks:
            invalid("task ids must be unique plain numbers")
        if not isinstance(supplied["owner"], str) or supplied["owner"] not in members:
            invalid("unknown task owner")
        for key in ("why", "outcome", "stop_rule"):
            identifier(supplied[key], key)
        if type(supplied["value"]) not in (int, float) or not math.isfinite(supplied["value"]):
            invalid("task value must be finite")
        if not isinstance(supplied["claims"], dict) or not supplied["claims"]:
            invalid("tasks need checkable claims")
        for claim, check in supplied["claims"].items():
            if not re.fullmatch(r"[A-Za-z0-9_-]+", claim):
                invalid("claim names must be plain tokens")
            if isinstance(check, dict) and "check" in check:
                object_fields(check, {"check", "timeout_seconds"}, {"check", "timeout_seconds"})
                if (not isinstance(check["check"], list) or not check["check"] or
                        not all(isinstance(arg, str) and arg and "\0" not in arg for arg in check["check"])):
                    invalid("a verifier check is a nonempty argv list of strings; no shell")
                timeout = check["timeout_seconds"]
                if (type(timeout) not in (int, float) or not math.isfinite(timeout) or
                        not 0 < timeout <= VERIFIER_LIMIT):
                    invalid(f"verifier timeout_seconds must be positive and at most {VERIFIER_LIMIT}")
                # Only the trusted plan names commands; the lead pins where they run.
                check["cwd"] = str(project)
                check["pins"] = verifier_pins(check["check"], check["cwd"])
                continue
            object_fields(check, {"path", "sha256"}, {"path", "sha256"})
            local_path(root, check["path"])
            if not isinstance(check["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", check["sha256"]):
                invalid("each claim requires the expected SHA-256")
        # Round 3 (S-2): unhashable kind values crash set membership before any
        # structured refusal; the string check must come first.
        if "kind" in supplied and (not isinstance(supplied["kind"], str) or
                                   supplied["kind"] not in {
                                       "research", "implementation", "review", "bounded experiment"}):
            invalid("kind must be research, implementation, review, or bounded experiment")
        if "workflow" in supplied:
            # Ticket 14: the lead's methodology selection travels with the brief, so a
            # member's harness default can never silently replace the parent's workflow.
            workflow = supplied["workflow"]
            object_fields(workflow, {"methodology", "phase", "skills", "scheduler", "integration_owner"}
                          | set(MATT_CONTEXT) | {"implement", "grilling", "route_decision", "cut",
                                                  "attention_minutes"}, {"methodology"})
            identifier(supplied["workflow"]["methodology"], "methodology")
            if "attention_minutes" in workflow and (
                    type(workflow["attention_minutes"]) not in (int, float) or
                    not math.isfinite(workflow["attention_minutes"]) or workflow["attention_minutes"] <= 0):
                invalid("attention_minutes must be a positive finite number")
            for key in ("phase", "scheduler", "integration_owner"):
                if key in supplied["workflow"]:
                    identifier(supplied["workflow"][key], key)
            # Round 3 (S-1/R-3): skills belongs to the workflow object; the old
            # "skills" in supplied guard was unreachable and let malformed values
            # through to crash brief generation.
            if "skills" in supplied["workflow"] and (
                    not isinstance(supplied["workflow"]["skills"], list) or
                    not all(isinstance(s, str) and s.strip()
                            for s in supplied["workflow"]["skills"])):
                invalid("workflow skills must be a list of required skill paths")
            if matt_task(supplied):
                object_fields(workflow, {"methodology", "phase", "skills", "scheduler",
                                        "integration_owner", "implement", "grilling",
                                        "route_decision", "cut", "attention_minutes"} | set(MATT_CONTEXT),
                              {"methodology", "phase", "skills"} | set(MATT_CONTEXT))
                for key in MATT_CONTEXT:
                    identifier(workflow[key], "workflow " + key)
                if "implement" in workflow:
                    identifier(workflow["implement"], "workflow implement")
                if "grilling" in workflow:
                    single_line(workflow["grilling"], "workflow grilling")
                if "route_decision" in workflow:
                    single_line(workflow["route_decision"], "workflow route_decision")
                if "cut" in workflow:
                    # Each Cut line becomes one Workflow line in the brief; the validator judges its quote and source.
                    if not isinstance(workflow["cut"], (str, list)) or workflow["cut"] == []:
                        invalid("workflow cut must be one line or a nonempty list of lines")
                    for value in cut_lines(workflow):
                        single_line(value, "workflow cut")
                if not Path(workflow["state"]).expanduser().is_absolute():
                    invalid("Matt workflow state must be an absolute authoritative record path")
            else:
                object_fields(workflow, {"methodology", "phase", "skills", "scheduler",
                                        "integration_owner", "attention_minutes"}, {"methodology"})
        for key in ("planned_commands", "files_changed", "after"):
            if key in supplied and (not isinstance(supplied[key], list) or
                                   not all(isinstance(x, str) for x in supplied[key])):
                invalid(key + " must be a list of strings")
        if "required" in supplied and type(supplied["required"]) is not bool:
            invalid("required must be boolean")
        if not isinstance(supplied.get("help_answers", {}), dict) or not isinstance(supplied.get("requests", []), list):
            invalid("help_answers must be an object and requests an array")
        for question, answer in supplied.get("help_answers", {}).items():
            identifier(question, "question")
            identifier(answer, "answer")
        for request in supplied.get("requests", []):
            object_fields(request, {"question", "recommendation"}, {"question", "recommendation"})
            identifier(request["question"], "question")
            identifier(request["recommendation"], "recommendation")
        tasks[tid] = {**supplied, "active": tid, "status": "queued", "return": f"tasks/{tid}.md"}
    if not tasks or any(dep not in tasks for t in tasks.values() for dep in t.get("after", [])):
        invalid("tasks and known dependency ids required")
    # Ticket 11: a self-dependency or cycle passes the existence check above but can
    # never become ready, so it is refused here, before any record exists.
    for tid, task in tasks.items():
        if tid in task.get("after", []):
            invalid("task " + tid + " cannot depend on itself")
    topological_order(tasks)
    if not (project / "AGENTS.md").is_file():
        invalid("project_root must contain AGENTS.md for the compliance gate")
    for task in tasks.values():
        if matt_task(task):
            brief(task, local_path(root, task["return"]))
    root.mkdir(parents=True, exist_ok=True)
    state = {**{k: params[k] for k in ("mission", "workspace_id", "lead_pane_id")},
             "project_root": str(project), "members": members, "tasks": tasks,
             "progress": [], "pending": [], "seen": [], "read_states": {},
             "namespace": uuid.uuid4().hex[:12], "turn": 0, "escalations": []}
    if "wake" in params:
        state["wake"] = params["wake"]
    with record_lock(root):
        # Checked under the lock so two inits cannot both see an empty record; the lock file is ours.
        if any(entry.name != ".lead.lock" for entry in root.iterdir()):
            raise Refusal("record_exists", "init requires an empty new record; use lead to resume")
        write(root, "agreement.md",
              f"# Agreement v1\n\nRecord root: {root}\n\n"
              "Channel: herdr socket; explicit workspace/pane ids; never focus.\n"
              "Doorbell: DONE <id> <path>; HELP/HELD/STOPPED <id> <detail>.\n"
              "Latitude: look, propose, do-tell, own.\n"
              "Authorized: local reversible brief, answer and artifact checks.\n"
              "Reserved: human alone chooses models, hiring, destructive actions, publishing and spending.\n"
              "Definition of done: validated receipt, exact Closes id, every claim passed at "
              "the current artifact digest and independently matched to the agreed digest.\n"
              "Brief additions: corrections use separate tasks/<attempt>.md files; "
              "HELP and human answers are durable files the member reads without pane typing.\n"
              "One writer: lead owns shared records and briefs; member owns its receipt section "
              "and sidecars after dispatch; human owns human-answers/. No lead overwrites a return.\n")
        write(root, "lessons.md", "# Lessons\n\nNo checked lesson yet.\n")
        for name in members:
            write(root, f"people/{name}.md", f"# {name}\n\n"
                  "Strengths: supplied mission assignment, not model reputation.\n"
                  "Tool ledger: local files and terminal only; no model or network invocation.\n"
                  "Development target: explicit revision-anchored claims and honest stops.\n")
        record(root, state, {"moment": "M1", "action": "take-team", "reason": "new scoped mission"})
    return {"record_root": str(root), "action": "initialized"}


class BoundedReader:
    """Nonblocking regular-file reads under per-file and aggregate caps, one per gate or delivery."""

    def __init__(self, max_bytes=DELIVERY_LIMIT, max_reads=128, confine=None):
        """`confine` is a set of roots the opened file must really be under. The caller passes a path it has already
        resolved, so nothing here resolves it a second time: the check and the read act on one opened object."""
        self.left, self.reads, self.confine = max_bytes, max_reads, confine

    def bytes(self, path):
        path = Path(path).expanduser()
        if self.confine is None:
            path = path.resolve()
        if self.reads <= 0:
            raise OSError(f"bounded read cap reached before {path}")
        self.reads -= 1
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            if self.confine is not None and not within(opened_path(stream.fileno()),
                                                       [base.resolve() for base in self.confine]):
                raise OSError(f"opened file is outside the allowed roots: {path}")
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > PROCEDURE_LIMIT:
                raise OSError(f"not a bounded regular file: {path}")
            data = stream.read(min(PROCEDURE_LIMIT, self.left) + 1)
        if len(data) > PROCEDURE_LIMIT or len(data) > self.left:
            raise OSError(f"bounded byte cap reached reading {path}")
        self.left -= len(data)
        return data

    def text(self, path):
        return self.bytes(path).decode("utf-8")

    def digest(self, path):
        return hashlib.sha256(self.bytes(path)).hexdigest()


def parent_gate(state_path, gate):
    """Run the existing workflow check on the lead's own parent record; Team Lead keeps phase choice."""
    path = Path(state_path).expanduser()
    reader = BoundedReader()
    try:
        text = reader.text(path)
    except (OSError, UnicodeError) as error:
        return [f"{path}: parent record unavailable: {error}"]
    try:
        return contracts.validate_workflow(text, path, gate=gate,
                                           read_text=reader.text, body_digest=reader.digest)
    except (OSError, UnicodeError) as error:
        return [f"{path}: {error}"]


def deliver(root, task, path):
    """Copy each selected procedure's exact bytes into an immutable packet before dispatch."""
    folder = f"tasks/{task['active']}/delivery"
    rows, copies, reader = [], [], BoundedReader()
    for index, value in enumerate(task["workflow"].get("skills", []), 1):
        resolved = contracts.workflow_path(value, path).resolve()
        try:
            data = reader.bytes(resolved)
            text = data.decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise Refusal("procedure_unavailable", f"cannot deliver selected procedure {resolved}: "
                          f"{error}") from error
        name = re.sub(r"[^A-Za-z0-9_.-]", "-", f"{resolved.parent.name}-{resolved.name}")
        copy = f"{folder}/{index:02d}-{name}"
        rows.append({"selected": value, "resolved": str(resolved),
                     "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "copy": copy})
        copies.append((copy, data, text))
    manifest = json.dumps({"attempt": task["active"], "procedures": rows,
                           "scope": "selected bodies only; delivery is not reading or application"},
                          indent=2) + "\n"
    relative = folder + "/manifest.json"
    existing = local_path(root, relative)
    if os.path.lexists(existing):
        # A crash after delivery leaves a packet; reuse it only when byte-identical.
        # The manifest gets its own one-read budget so copies replay under first delivery's body caps.
        replay = BoundedReader()
        try:
            same = BoundedReader(max_reads=1).bytes(existing) == manifest.encode("utf-8") and all(
                replay.bytes(local_path(root, copy)) == data for copy, data, _ in copies)
        except OSError as error:
            raise Refusal("delivery_mismatch", f"earlier delivery packet unreadable: {error}") from error
        if not same:
            raise Refusal("delivery_mismatch", "an earlier delivery packet differs; reconcile, never overwrite")
        return rows, relative
    for copy, _, text in copies:
        write(root, copy, text)
        local_path(root, copy).chmod(0o444)
    write(root, relative, manifest)
    local_path(root, relative).chmod(0o444)
    return rows, relative


def brief(task, path=None, delivery=None):
    attempt = f"attempt: {task['active']}\n" if "." in task["active"] else ""
    kind = f"kind: {task['kind']}\n" if task.get("kind") else ""
    text = (f"---\ntask: {task['id']}\n{attempt}owner: {task['owner']}\nlatitude: do-tell\n{kind}"
            f"return: {task['return']}\n---\n\n# Task {task['active']}\n\n"
            f"## Why\n{task['why']}\n\n## Outcome\n{task['outcome']}\n\n## Done means\n")
    for name, check in task["claims"].items():
        if "check" in check:
            text += (f"- {name}: lead runs {json.dumps(check['check'])} in {check['cwd']} "
                     f"(timeout {check['timeout_seconds']}s)\n")
        else:
            text += f"- {name}: {check['path']} sha256 {check['sha256']}\n"
    if task.get("workflow"):
        # Ticket 14: the methodology selection travels with the brief so a member's
        # harness default can never silently replace the parent's workflow.
        workflow = task["workflow"]
        text += f"\n## Workflow\nMethodology: {'matt' if matt_task(task) else workflow['methodology']}"
        if matt_task(task):
            text += f"\nExecutor: {task['owner']}"
            for key, label in MATT_CONTEXT.items():
                text += f"\n{label}: {workflow[key]}"
            if "implement" in workflow:
                text += f"\nImplement: {workflow['implement']}"
            if "grilling" in workflow:
                text += f"\nGrilling: {workflow['grilling']}"
            if "route_decision" in workflow:
                text += f"\nRoute decision: {workflow['route_decision']}"
            if "cut" in workflow:
                text += "".join(f"\nCut: {value}" for value in cut_lines(workflow))
        if workflow.get("phase"):
            text += f"\nPhase: {workflow['phase']}"
        if workflow.get("skills"):
            text += "\nRequired skill paths: " + ", ".join(workflow["skills"])
        if workflow.get("scheduler"):
            text += f"\nScheduler: {workflow['scheduler']}"
        if workflow.get("integration_owner"):
            text += f"\nIntegration owner: {workflow['integration_owner']}"
        text += ("\nYou inherit this selection; your harness's default cannot silently "
                 "replace this workflow.\n")
    if delivery:
        rows, manifest = delivery
        text += (f"\n## Delivered procedures\nManifest: {manifest}\n"
                 "The lead copied these exact selected bytes before dispatch. Read each body "
                 "completely and record your own Loaded line for its selected path; delivery is "
                 "not reading or application.\n")
        text += "".join(f"- {row['selected']} | sha256:{row['sha256']} bytes:{row['bytes']} | "
                        f"{row['copy']}\n" for row in rows)
    return checked("brief", text + f"\n## Stop rule\n{task['stop_rule']}\n\n"
                   f"## Return\nAppend your receipt here. Ring DONE {task['active']} {task['return']}.\n",
                   path, matt=matt_task(task))


class DispatchClient:
    """Carry the lead's pin through every adapter guard snapshot and pre-send."""

    def __init__(self, client, identity):
        self.client, self.identity = client, dict(identity)

    def __getattr__(self, name):
        return getattr(self.client, name)

    def snapshot(self):
        snapshot = self.client.snapshot()
        for collection in ("agents", "panes"):
            matches = [row for row in snapshot[collection]
                       if row.get("pane_id") == self.identity["pane_id"]]
            keys = [k for k in self.identity if collection == "agents" or k != "name"]
            if len(matches) != 1 or any(matches[0].get(k) != self.identity[k] for k in keys):
                raise Refusal("identity_mismatch", "dispatch identity differs from lead look; reconcile member")
        return snapshot

    def request(self, method, params):
        if method == "pane.send_input":
            # No server-side compare-and-send exists; retain the pin up to this boundary.
            self.snapshot()
        return self.client.request(method, params)


def receipt_suffix(task, text):
    if not text.startswith(task["brief_text"]):
        raise Refusal("receipt_mismatch", "member changed the lead-owned brief")
    return text[len(task["brief_text"]):]


def above_input(text, start):
    """Visible lines above the editable input frame, which begins at a line that is exactly its start token."""
    lines = []
    for line in text.splitlines():
        if line.rstrip() == start:
            break
        lines.append(line)
    return lines


def look(client, root, state):
    picture = observe(client, {"workspace_id": state["workspace_id"]})
    for name, member in state["members"].items():
        matches = [m for m in picture["members"] if m["pane_id"] == member["pane_id"]]
        if len(matches) != 1:
            raise Refusal("member_missing", "member absent: " + name)
        live = matches[0]
        identity = {k: live.get(k) for k in ("pane_id", "workspace_id", "tab_id", "terminal_id",
                                            "cwd", "agent", "name")}
        if any(not isinstance(v, str) or not v for k, v in identity.items() if k != "name"):
            raise Refusal("identity_mismatch", "member identity incomplete")
        if identity["agent"] != member["input_box"]["agent"]:
            raise Refusal("identity_mismatch", "agent kind changed")
        if "identity" in member and member["identity"] != identity:
            raise Refusal("identity_mismatch", "member replaced; reconcile explicitly")
        member["identity"] = identity
        member["status"] = live.get("agent_status")
        signature = [live.get("state_change_seq"), live.get("agent_status")]
        unfinished = any(t["owner"] == name and t["status"] not in
                         {"queued", "accepted", "refused", "stopped", "review-refused"}
                         for t in state["tasks"].values())
        # Ticket 15 / spec story 32: this one signature-stable reread per turn is
        # authorized for members holding unfinished work, because a transition read
        # can miss a late doorbell line still inside the viewport. Everyone else is
        # read on transitions only, never continuously.
        if (state["read_states"].get(name) == signature and
                member["status"] != "blocked" and not unfinished):
            continue
        read = client.request("pane.read", {
            "pane_id": member["pane_id"], "source": "visible", "format": "text", "strip_ansi": True,
        }).get("read", {})
        if read.get("pane_id") != member["pane_id"] or read.get("truncated") is not False:
            raise Refusal("output_unreadable", "cannot read member transition")
        if not isinstance(read.get("text"), str):
            raise Refusal("output_unreadable", "missing visible output")
        rings = [line.strip() for line in above_input(read["text"], member["input_box"]["start"])
                 if not contracts.parse_doorbell(line)[1]]
        counts = {}
        for line in rings:
            counts[line] = counts.get(line, 0) + 1
        # A ring released by a human continue stays suppressed while its old copy is what is visible; a
        # new identical ring raises the visible count, and a line that left the viewport is free again.
        # An unknown count (saved by an older lead) cannot tell a repeat from the old copy, so it releases.
        for task in state["tasks"].values():
            stale = task.get("stale_rings", {}) if task["owner"] == name else {}
            for text, count in list(stale.items()):
                now = counts.get(text, 0)
                if now == 0 or count is None or now > count:
                    del stale[text]
                else:
                    stale[text] = now
        # The visible count before a human answer is the baseline that answer releases from.
        state.setdefault("ring_counts", {})[name] = counts
        for line in rings:
            enqueue(root, state, name, line, "pane")
        state["read_states"][name] = signature
    # A durable receipt still stands when a bell was missed or wrapped offscreen.
    for task in state["tasks"].values():
        seen = return_status(root, task)
        if seen:
            path = local_path(root, task["return"])
            try:
                # Set once, and only for a matching Closes suffix actually seen: an unjudgeable return
                # still goes to review but leaves returned_at UNKNOWN. A later rewrite must not move it.
                if seen == "closes":
                    task.setdefault("returned_at", {}).setdefault(task["active"], datetime.fromtimestamp(
                        path.stat().st_mtime, timezone.utc).isoformat())
            except OSError:
                pass
            enqueue(root, state, task["owner"], done_line(task), "disk")
    return picture


def return_status(root, task):
    """'closes' when an in-flight task's return file closes its active attempt; 'unjudged' when it cannot be
    judged (review decides); otherwise None."""
    path = local_path(root, task["return"])
    if task["status"] not in IN_FLIGHT or not path.exists():
        return None
    try:
        suffix = receipt_suffix(task, BoundedReader(max_reads=1).text(path))
        return "closes" if task["active"] in contracts.CLOSES_LINE_RE.findall(suffix) else None
    except (Refusal, OSError, UnicodeError):
        return "unjudged"  # Let review record a changed-prefix or unreadable return, never accept it.


def closing_return(root, task):
    """True when an in-flight task's return file closes its active attempt, or cannot be judged."""
    return return_status(root, task) is not None


def done_line(task):
    return f"DONE {task['active']} {task['return']}"


def done_revision(root, task):
    path = local_path(root, task["return"])
    try:
        return BoundedReader(max_reads=1).digest(path) if path.exists() else "missing"
    except OSError:
        return "unreadable"


def new_returns(root, state):
    """Return files that close an in-flight attempt at a revision no lead turn has queued yet."""
    return [{"task": task["id"], "attempt": task["active"], "member": task["owner"], "return": task["return"]}
            for task in state["tasks"].values() if closing_return(root, task) and
            "\0".join([task["owner"], task["active"], done_line(task), done_revision(root, task)])
            not in state["seen"]]


def enqueue(root, state, member, line, source):
    ring, errors = contracts.parse_doorbell(line)
    if errors:
        raise Refusal("contract_invalid", "; ".join(errors))
    task = state["tasks"].get(ring["task"], {})
    active = task.get("active", "")
    if line in task.get("stale_rings", {}):
        return
    key = member + "\0" + active + "\0" + line
    if ring["type"] == "DONE" and active == (ring["attempt"] or ring["task"]) and task["owner"] == member:
        key += "\0" + done_revision(root, task)
    if key not in state["seen"]:
        state["seen"].append(key)
        state["pending"].append({**ring, "member": member, "line": line, "source": source})


def send_task(client, root, state, task, options):
    if matt_task(task):
        gate = "review" if "review" in {task.get("kind"), task["workflow"].get("route")} else "entry"
        errors = parent_gate(task["workflow"]["state"], gate)
        if errors:
            raise Refusal("parent_gate", f"parent workflow {gate} gate: " + "; ".join(errors))
    member = state["members"][task["owner"]]
    evidence = {"task": task["id"], "attempt": task["active"], "member": task["owner"],
                "planned_commands": task["planned_commands"], "files_changed": task["files_changed"]}
    gate = compliance.gate_dispatch(Path(state["project_root"]), evidence)
    write_json(root, f"tasks/{task['active']}/gate.json", gate)
    compliance.record_report(root, gate["report"])
    if gate["decision"] != "allow":
        task["status"] = "refused"
        return {"moment": "M2", "action": "compliance-refused", "task": task["active"],
                "reason": "; ".join(gate["reasons"])}
    path = local_path(root, task["return"])
    if path.exists():
        raise Refusal("brief_exists", "reconcile existing task artifact, never overwrite")
    delivery = deliver(root, task, path) if matt_task(task) else None
    text = brief(task, path, delivery)
    task.setdefault("git_base", {})[task["active"]] = git_head(state["project_root"])
    write(root, task["return"], text)
    task["brief_text"] = text
    task["status"] = "dispatching"
    record(root, state, {"moment": "M2", "action": "prepared", "task": task["active"],
                         "reason": "task line persisted before dispatch"})
    try:
        sent = dispatch(DispatchClient(client, member["identity"]), {
            "workspace_id": state["workspace_id"], "pane_id": member["pane_id"],
            "dispatch_id": state["namespace"] + "-" + task["active"],
            "text": f"Read brief {path}. Return there; honor done-means and stop rule.",
            "input_box": member["input_box"],
        }, options)
    except Refusal as error:
        # A resume deadline can fire after input was written, so it is as uncertain as a lost reply.
        uncertain = {"dispatch_uncertain", "duplicate_dispatch", "resume_budget"}
        task["status"] = "uncertain" if error.code in uncertain else "refused"
        return {"moment": "M2", "action": task["status"], "task": task["active"],
                "reason": str(error), "code": error.code}
    task["status"] = "sent"
    return {"moment": "M2", "action": "dispatch", "task": task["active"],
            "reason": "idle member with highest-value independent work", "dispatch": sent}


def pick(state):
    candidates = []
    for ring in state["pending"]:
        candidates.append((PRIORITY[ring["type"]], 0, ring))
    for task in state["tasks"].values():
        # review-refused is terminal for the owner: without it in the set, one
        # refused optional task kept the member busy forever and an independent
        # required task for the same owner never dispatched.
        if assignable(state, task):
            candidates.append((PRIORITY["assign"], task["value"], {"assign": task["id"]}))
    # Stable tie order is plan order, not a cursor or round-robin poll.
    candidates.sort(key=lambda item: (-item[0], -item[1]))
    return candidates


def git(project, *args, check=True):
    # Only ref, commit and index reads: comparing worktree content runs repository clean/process filters.
    # Inherited GIT_DIR/GIT_WORK_TREE would point -C elsewhere; repository config can name an fsmonitor
    # hook, and a partial clone's promisor remote would run on a missing object.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(["git", "-C", project, "-c", "core.fsmonitor=false", "--no-optional-locks",
                           "--no-lazy-fetch", "--no-replace-objects", *args], check=check, env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=GIT_TIMEOUT)


def git_unavailable(error):
    detail = getattr(error, "stderr", None) or str(error)
    if isinstance(detail, bytes):  # TimeoutExpired keeps raw bytes even with text=True.
        detail = detail.decode(errors="replace")
    return "unavailable: " + detail.strip()[:200]


def git_head(project):
    try:
        return git(project, "rev-parse", "--verify", "HEAD").stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        return git_unavailable(error)


def git_window(state, task):
    """Evidence only: the shared project's commits since this attempt's dispatch, never a verdict."""
    base = task.get("git_base", {}).get(task["active"], "unavailable: no dispatch base recorded")
    if base.startswith("unavailable"):
        return base
    project = state["project_root"]
    try:
        head = git(project, "rev-parse", "--verify", "HEAD").stdout.strip()
        ancestry = git(project, "merge-base", "--is-ancestor", base, head, check=False)
        if ancestry.returncode not in (0, 1):
            raise subprocess.CalledProcessError(ancestry.returncode, "merge-base", stderr=ancestry.stderr)
        ahead = int(git(project, "rev-list", "--count", f"{base}..{head}").stdout)
        commits = git(project, "rev-list", "--max-count=20", f"{base}..{head}").stdout.split()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return git_unavailable(error)
    return {"base": base, "head": head, "base_is_ancestor": ancestry.returncode == 0,
            "commits_ahead": ahead, "commits": commits,
            "worktree": "not collected: Git content comparison can run repository helpers"}


def pinned_digest(path):
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            size += len(chunk)
            if size > MAX_PIN_BYTES:
                raise ValueError(f"larger than {MAX_PIN_BYTES} bytes")
            digest.update(chunk)
    return digest.hexdigest()


def resolve_head(argv0, cwd):
    """The executable argv[0] names, resolved once against the pinned cwd, the directory the check runs in: a name with a
    slash is taken relative to it, and so is every relative (or empty) PATH entry. None when nothing executable is there.
    The lead stores this path, rechecks it and launches it, so the file it identified is the file it runs. The stored path
    is named as it was named: only `.` components and empty ones (repeated slashes) are dropped, and every `..` and every
    symlink stays, so the kernel resolves it exactly as it resolves a direct run (`link/..` is the parent of link's target,
    not of link) and a program that finds its venv from the path it was started by, such as a venv's bin/python, sees the
    same path. Nothing is resolved here, so the stored head can contain `..`."""
    if "/" in argv0:
        found = shutil.which(os.path.join(cwd, argv0))
    else:
        entries = [os.path.join(cwd, entry) for entry in os.environ.get("PATH", os.defpath).split(os.pathsep)]
        found = shutil.which(argv0, path=os.pathsep.join(entries))
    if not found:
        return None
    parts = [part for part in found.split(os.sep) if part not in ("", ".")]
    return os.sep + os.sep.join(parts)


def verifier_pins(argv, cwd):
    """Identity of the files a trusted check names, taken when the plan is admitted: argv[0] resolved against the pinned
    cwd and PATH (a check whose argv[0] resolves to nothing is refused), and every other argument that is an existing
    regular file (absolute, or relative to the pinned cwd). Directories, module names and files the checker opens itself
    are not pinned; see LEAD.md."""
    def pin(path):
        try:
            return {"path": str(path), "sha256": pinned_digest(path)}
        except (OSError, ValueError) as error:
            raise Refusal("schema_invalid", f"a verifier file cannot be pinned: {path}: {error}") from error

    head = resolve_head(argv[0], cwd)
    if head is None:
        raise Refusal("schema_invalid", f"verifier {argv[0]} is not an executable file in the pinned cwd {cwd} or on PATH; "
                      "name it by absolute path, or put it in a PATH entry that exists")
    files, seen = [], {head}
    for arg in argv[1:]:
        path = Path(arg) if os.path.isabs(arg) else Path(cwd) / arg
        if str(path) not in seen and path.is_file():
            seen.add(str(path))
            files.append(pin(path))
    return {"head": pin(head), "files": files}


def recheck_pins(check):
    """Before the lead runs a trusted check: every file it named at admission must still be the same bytes. A missing or
    changed file holds the task (verifier_unverified); a check that cannot be identified never accepts anything.
    Returns the pinned executable, which is what the lead launches."""
    pins = check.get("pins")
    if (not isinstance(pins, dict) or not isinstance(pins.get("head"), dict) or
            not isinstance(pins.get("files"), list)):
        raise Refusal("verifier_unverified", "no identity pins were recorded for this check; admit the plan again")
    head = pins["head"]
    if not isinstance(head.get("path"), str) or not head["path"]:
        raise Refusal("verifier_unverified", "no executable was pinned for this check; admit the plan again")
    problems = []
    for pin in [head] + pins["files"]:
        try:
            changed = pinned_digest(pin["path"]) != pin["sha256"]
        except (OSError, ValueError, KeyError, TypeError):
            problems.append(f"verifier file missing since admission: {pin.get('path') if isinstance(pin, dict) else pin}")
            continue
        if changed:
            problems.append(f"verifier file changed since admission: {pin['path']}")
    if problems:
        raise Refusal("verifier_unverified", "; ".join(problems) + "; the claim is unverified, not failed")
    return head["path"]


def run_verifier(check):
    """Run one trusted plan command; a command named in a member receipt never runs."""
    head = recheck_pins(check)
    started = time.monotonic()
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen([head] + check["check"][1:], cwd=check["cwd"], stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as error:
            raise Refusal("verifier_unverified", f"verifier could not start: {error}") from error
        code = None
        try:
            code = process.wait(timeout=check["timeout_seconds"])
        except subprocess.TimeoutExpired:
            pass
        finally:
            if code is None:
                # The leader is unreaped, so its group id cannot name another process.
                # macOS answers EPERM once only that zombie leader remains.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                process.wait()
        if code is None:
            raise Refusal("verifier_unverified", f"verifier exceeded {check['timeout_seconds']}s; "
                          "the claim is unverified, not failed")
        output.seek(0)
        digest, size = hashlib.sha256(), 0
        for chunk in iter(lambda: output.read(65536), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"exit": code, "seconds": round(time.monotonic() - started, 3),
            "output_sha256": digest.hexdigest(), "output_bytes": size}


def review_receipt(root, task, ring, text=None, contract_read_text=None, contract_body_digest=None,
                   contract_path=None, run_checks=True):
    path = local_path(root, ring["artifact"])
    if path != local_path(root, task["return"]):
        raise Refusal("receipt_mismatch", "DONE did not name the assigned return path")
    # Round 3 (S-3): a caller that already hashed the receipt passes those exact
    # bytes, so the reviewed text and the recorded digest can never describe
    # different writes of the same file.
    full_text = text if text is not None else BoundedReader(max_reads=1).text(path)
    text = receipt_suffix(task, full_text)
    checked("receipt", full_text if matt_task(task) else text, contract_path or path, matt=matt_task(task),
            read_text=contract_read_text, body_digest=contract_body_digest)
    portions = [p for _, p in contracts.split_returns(text)
                if contracts.CLOSES_LINE_RE.findall(p) == [task["active"]]]
    if len(portions) != 1 or contracts.CLOSES_LINE_RE.findall(text) != [task["active"]]:
        raise Refusal("receipt_mismatch", "receipt must close exactly this attempt once")
    claims = contracts.find_section(contracts.sections(portions[0], 3), "Claims")
    reported = {}
    for line in claims.splitlines():
        match = contracts.CLAIM_RE.match(line.strip())
        if match:
            name = match["claim"]
            if name in reported:
                raise Refusal("receipt_mismatch", "duplicate claim: " + name)
            reported[name] = (match["status"], line)
    errors, evidence = [], []
    for name, check in task["claims"].items():
        status, line = reported.get(name, ("untested", ""))
        if "check" in check:
            if status != "passed":
                errors.append(name + ": missing passing claim")
            evidence.append({"claim": name, "check": check["check"], "reported_status": status,
                             "verifier": "deferred"})
            continue
        sidecar = local_path(root, check["path"])
        digest = hashlib.sha256(sidecar.read_bytes()).hexdigest() if sidecar.is_file() else None
        if status != "passed" or not digest or f"sha256 {digest}" not in line:
            errors.append(name + ": missing passing claim at the actual artifact digest")
        if digest != check["sha256"]:
            errors.append(name + ": artifact differs from agreed SHA-256")
        evidence.append({"claim": name, "path": check["path"], "sha256": digest,
                         "expected_sha256": check["sha256"], "reported_status": status})
    if run_checks:
        run_deferred(task, errors, evidence)
    return errors, evidence


def run_deferred(task, errors, evidence):
    unverified = []
    for row in evidence:
        if row.get("verifier") == "deferred":
            del row["verifier"]
            try:
                row.update(run_verifier(task["claims"][row["claim"]]))
            except Refusal as error:
                row["unverified"] = str(error)
                unverified.append(f"{row['claim']}: {error}")
                continue
            if row["exit"] != 0:
                errors.append(f"{row['claim']}: trusted verifier exited {row['exit']}")
    # A known failure already takes the correction path; an unverifiable sibling must not hide it.
    if unverified and not errors:
        raise Refusal("verifier_unverified", "; ".join(unverified))
    errors.extend(unverified)


def act_ring(root, state, ring):
    state["pending"].remove(ring)
    task = state["tasks"].get(ring["task"])
    active = ring["attempt"] or ring["task"]
    common = {"moment": "M5" if ring["type"] == "DONE" else "M4",
              "task": active, "member": ring["member"], "doorbell": ring["line"]}
    if (not task or task["owner"] != ring["member"] or task["active"] != active or
            task["status"] in {"queued", "accepted", "refused", "stopped", "review-refused"}):
        return {**common, "action": "reject-doorbell",
                "reason": "not the owner or open attempt; current attempt " +
                (task["active"] if task else "unknown")}
    if ring["type"] == "HELP":
        answer = task.get("help_answers", {}).get(ring["detail"])
        if answer is None:
            return escalate(root, state, [ring], common)
        relative = f"answers/{active}.md"
        write(root, relative, f"# HELP {active}\n\nQuestion: {ring['detail']}\n\n"
              f"Lead answer: {answer}\n\nResume only within the original brief's authority.\n")
        task["status"] = "help-answered"
        return {**common, "action": "answer-help", "answer": answer, "evidence": relative,
                "reason": "blocked member outranks reports and idle assignments"}
    if ring["type"] == "HELD":
        return escalate(root, state, [ring], common)
    if ring["type"] == "STOPPED":
        task["status"] = "stopped"
        return {**common, "action": "stop", "reason": ring["detail"], "evidence": task["return"]}
    try:
        errors, evidence = review_receipt(root, task, ring)
    except (Refusal, OSError, UnicodeError) as error:
        if getattr(error, "code", None) == "verifier_unverified":
            # An unverified claim is neither a pass nor a worker failure; the human decides.
            task["verifier_held"] = True
            return escalate(root, state, [{**ring, "detail": str(error)}], common)
        retryable = getattr(error, "code", None) == "contract_invalid" or isinstance(error, FileNotFoundError)
        task["status"] = "review-pending" if retryable else "review-refused"
        if retryable:
            idle = state["members"][task["owner"]].get("status") in {"idle", "done"}
            task["idle_review_turns"], task["review_digest"] = int(idle), return_digest(root, task)
        return {**common, "action": "receipt-pending" if retryable else "receipt-refused",
                "reason": str(error)}
    proof = f"reviews/{active}.json"
    write_json(root, proof, {"attempt": active, "receipt": task["return"],
                            "errors": errors, "checks": evidence, "at": stamp()})
    if errors:
        if "." in active:
            task["status"] = "stopped"
            return {**common, "action": "stop", "reason": "two-attempt cap: " + "; ".join(errors),
                    "evidence": proof}
        task.update(active=task["id"] + ".2", status="queued")
        task["return"] = f"tasks/{task['active']}.md"
        task["outcome"] += " Correction: re-check the agreed claims; the previous artifact failed review."
        people = local_path(root, f"people/{task['owner']}.md")
        write(root, str(people.relative_to(root)), people.read_text() +
              f"\nCorrection {active}: {proof}. Lead checked its brief first; retain do-tell "
              "latitude with smaller, explicit claim checks. No model judgment.\n")
        return {**common, "action": "correct", "next_attempt": task["active"],
                "reason": "; ".join(errors), "evidence": proof}
    task["status"] = "accepted"
    task["accepted_evidence"] = proof
    return {**common, "action": "accept", "reason": "validated receipt and independently checked "
            "every claim at the current artifact digest; report outranks idle work", "evidence": proof}


def escalate(root, state, rings, common):
    for pending in list(state["pending"]):
        task = state["tasks"].get(pending["task"])
        unmapped = pending["type"] == "HELP" and task and pending["detail"] not in task.get("help_answers", {})
        if ((pending["type"] == "HELD" or unmapped) and task and task["owner"] == pending["member"] and
                task["active"] == (pending["attempt"] or pending["task"]) and
                task["status"] in {"sent", "help-answered", "uncertain", "dispatching"}):
            rings.append(pending)
            state["pending"].remove(pending)
    eid = str(len(state["escalations"]) + 1)
    requests = []
    for ring in rings:
        task = state["tasks"][ring["task"]]
        task["status"] = "held"
        requests += [{"task": task["active"], **r} for r in [{
            "question": ring["detail"],
            "recommendation": "Hold this decision; preserve models, roster and data. "
                              "Clarify an answer within the original scope.",
        }] + task.get("requests", [])]
    escalation = {"id": eid, "status": "waiting", "requests": requests,
                  "tasks": list(dict.fromkeys(r["task"] for r in rings))}
    state["escalations"].append(escalation)
    path = f"escalations/{eid}.md"
    lines = [f"# Human escalation {eid}", "", "Status: waiting", "",
             "One batch; no model switch, hiring or destructive operation is executed.", ""]
    for request in requests:
        lines += [f"## Task {request['task']}", f"Question: {request['question']}",
                  f"Lead recommendation: {request['recommendation']}",
                  "Scope: existing mission only. Cost/reversibility: no action taken; "
                  "retain current fleet until the human decides.", ""]
    write(root, path, "\n".join(lines))
    return {**common, "moment": "M9", "action": "escalate", "escalation": eid,
            "reason": "human-reserved decisions batched with lead recommendations", "evidence": path}


def validate_answer(response):
    required = {"escalation", "by", "decision", "answer"}
    try:
        object_fields(response, required, required)
        for key in required:
            identifier(response[key], key)
        if not re.fullmatch(r"[0-9]+", response["escalation"]) or response["decision"] not in {"continue", "stop"}:
            invalid("answer needs escalation id and continue/stop within original authority")
    except Refusal as error:
        raise Refusal("invalid_answer", "invalid human answer: " + str(error)) from error


def answer(params):
    required = {"record_root", "escalation", "by", "decision", "answer"}
    object_fields(params, required, required)
    root = Path(identifier(params["record_root"], "record_root")).resolve()
    response = {k: params[k] for k in required if k != "record_root"}
    validate_answer(response)
    with record_lock(root):
        state = load_state(local_path(root, "lead-state.json").read_text())
        if not any(e["id"] == params["escalation"] and e["status"] == "waiting" for e in state["escalations"]):
            raise Refusal("not_waiting", "no waiting escalation with this id")
        relative = f"human-answers/{params['escalation']}.json"
        if local_path(root, relative).exists():
            raise Refusal("answer_exists", "human answer already recorded")
        write_json(root, relative, response)
    return {"action": "answer-recorded", "evidence": relative}


def human_turn(root, state, escalation, read_text=Path.read_text):
    path = local_path(root, f"human-answers/{escalation['id']}.json")
    if not path.exists():
        return {"moment": "M9", "action": "wait-human", "reason": "human has not answered",
                "escalation": escalation["id"]}
    response = json_loads(read_text(path))
    validate_answer(response)
    if response["escalation"] != escalation["id"]:
        raise Refusal("invalid_answer", f"misfiled human answer: escalation {response['escalation']} "
                      f"does not match waiting escalation {escalation['id']}; correct {path}")
    relative = f"escalations/{escalation['id']}.md"
    old = read_text(local_path(root, relative))
    # Files first: a failed write must leave the escalation waiting and its tasks held in memory too.
    for tid in escalation["tasks"]:
        task = state["tasks"][tid]
        write(root, f"answers/{task['active']}-human.md",
              f"# Human answer for {task['active']}\n\nBy: {response['by']}\n"
              f"Decision: {response['decision']}\nAnswer: {response['answer']}\n\n"
              "No new model/hiring/destructive authority is granted by this command.\n")
    write(root, relative, old.replace("Status: waiting", "Status: answered", 1) +
          f"\n## Human answer\nBy: {response['by']}\n"
          f"Decision: {response['decision']}\n{response['answer']}\n")
    escalation["status"] = "answered"
    escalation["answer"] = response
    for tid in escalation["tasks"]:
        task = state["tasks"][tid]
        if response["decision"] == "stop":
            task["status"] = "stopped"
        else:
            if task.get("idle_review_turns", 0) >= IDLE_REVIEW_TURNS:
                # A continued stalled review stays monitored; another unchanged stall escalates again.
                task["status"], task["idle_review_turns"] = "review-pending", 0
                task["review_digest"] = return_digest(root, task)
            else:
                # A dependency hold was never sent; it returns to the queue, where the dead dependency fails it.
                task["status"] = "queued" if task.get("dependency_escalated") else "help-answered"
            # The member may ring the same HELD or HELP again; release it once the old copy is not what is seen.
            asked = tuple(f"{task['owner']}\0{task['active']}\0{kind} " for kind in ("HELD", "HELP"))
            # This turn's look has just recorded the visible counts; a released line no longer visible needs none.
            counts = state.get("ring_counts", {}).get(task["owner"], {})
            released = {key.split("\0")[2] for key in state["seen"] if key.startswith(asked)}
            task["stale_rings"] = {text: counts[text] for text in released if text in counts}
            state["seen"] = [key for key in state["seen"] if not key.startswith(asked)]
        if task.pop("verifier_held", False) and response["decision"] == "continue":
            # The unchanged receipt's DONE stays deduplicated by revision; release it for a recheck.
            prefix = f"{task['owner']}\0{task['active']}\0DONE "
            state["seen"] = [key for key in state["seen"] if not key.startswith(prefix)]
    return {"moment": "M9", "action": "human-answer", "reason": response["answer"],
            "evidence": relative, "escalation": escalation["id"]}


def close_mission(root, state):
    checks = []
    for task in state["tasks"].values():
        if task["status"] != "accepted":
            # Round 3 (R-2): review-refused is terminal like refused/stopped; an
            # optional task that failed review must not block closing forever.
            if task["status"] not in {"refused", "stopped", "review-refused"}:
                return {"moment": "M3", "action": "wait", "reason": "optional work still active"}
            if "not_run" in task:
                checks.append({"task": task["active"], "not_run": task["not_run"], "errors": []})
            continue
        try:
            errors, evidence = review_receipt(root, task, {"artifact": task["return"]})
        except (Refusal, OSError, UnicodeError) as error:
            errors, evidence = [str(error)], []
        checks.append({"task": task["active"], "errors": errors, "evidence": evidence})
    # A worker receipt is not parent completion: the parent's own accept gate must pass too.
    for parent in dict.fromkeys(t["workflow"]["state"] for t in state["tasks"].values() if matt_task(t)):
        checks.append({"parent_state": parent, "gate": "accept", "errors": parent_gate(parent, "accept")})
    write_json(root, "closing-checks.json", checks)
    return {"moment": "M10",
            "action": "completion-refused" if any(c["errors"] for c in checks) else "complete",
            "reason": "rechecked accepted artifacts on the combined final state",
            "evidence": "closing-checks.json"}


def return_digest(root, task):
    try:
        return BoundedReader(max_reads=1).digest(local_path(root, task["return"]))
    except OSError:
        return "unreadable"


def stalled_review(root, state):
    """Count consecutive turns that see a pending review's owner idle and its return unchanged."""
    stalled = None
    for task in state["tasks"].values():
        if task["status"] != "review-pending":
            continue
        digest = return_digest(root, task)
        if state["members"][task["owner"]].get("status") in {"idle", "done"} and digest == task.get("review_digest"):
            task["idle_review_turns"] = task.get("idle_review_turns", 0) + 1
        else:
            task["idle_review_turns"], task["review_digest"] = 0, digest
        if task["idle_review_turns"] >= IDLE_REVIEW_TURNS and stalled is None:
            stalled = task
    return stalled


def stop_unreachable_optional(state):
    """Optional queued work behind a dependency that ended without acceptance can never run; record it as not run."""
    stopped, changed = [], True
    while changed:
        changed = False
        for task in state["tasks"].values():
            if task["status"] != "queued" or task.get("required", True):
                continue
            dep = next((state["tasks"][d] for d in task.get("after", [])
                        if state["tasks"][d]["status"] in {"refused", "stopped", "review-refused"}), None)
            if dep:
                task["status"] = "stopped"
                task["not_run"] = f"dependency {dep['id']} ended {dep['status']} without acceptance"
                stopped.append(task["id"])
                changed = True
    return stopped


def dead_dependency(state):
    """A queued required task whose dependency ended without acceptance can never become ready."""
    for task in state["tasks"].values():
        if task["status"] == "queued" and task.get("required", True):
            for dep in task.get("after", []):
                if state["tasks"][dep]["status"] in {"refused", "stopped", "review-refused"}:
                    return task, state["tasks"][dep]
    return None


def fail_mission(root, state, reasons=()):
    """Ticket 12: required work that stopped is a durable failure, not an endless wait."""
    # Round 3 (R-2): review-refused is a terminal refusal of required work; leaving it
    # out let the turn chain return wait forever with no durable failure recorded.
    failed = [t for t in state["tasks"].values()
              if t.get("required", True) and t["status"] in {"refused", "stopped", "review-refused"}]
    evidence = "mission-failed.md"
    lines = ["# Mission failed", "",
             "Required work stopped or was refused without acceptance.",
             "No further lead turn is authorized; the human decides next.", ""]
    for task in failed:
        lines.append(f"- Task {task['active']} ({task['status']}): return {task['return']}")
    lines += [f"- {reason}" for reason in reasons]
    write(root, evidence, "\n".join(lines) + "\n")
    state["outcome"] = {"status": "failed", "evidence": evidence}
    return {"moment": "M10", "action": "mission-failed",
            "reason": "; ".join(reasons) or "required task stopped or refused without acceptance",
            "evidence": evidence}


STATE_SHAPE = {"members": dict, "tasks": dict, "progress": list, "pending": list, "seen": list,
               "read_states": dict, "escalations": list}


def load_state(text):
    """The durable index, refused before any use unless it has the container shape init wrote."""
    state = json_loads(text)
    if not isinstance(state, dict) or any(not isinstance(state.get(k), t) for k, t in STATE_SHAPE.items()):
        raise Refusal("record_corrupt", "lead-state.json is not a lead index; restore it from a saved copy, then "
                      "run resume with a new resume_id, or start a new authorized mission with a new record")
    return state


def resume_latched(root):
    # Presence, including an unreadable/broken marker, blocks before index loading.
    try:
        (root / ".resume-latch").lstat()
    except FileNotFoundError:
        return False
    return True


def turn(params, options):
    object_fields(params, {"record_root", "wait_seconds"}, {"record_root"})
    root = Path(identifier(params["record_root"], "record_root")).resolve()
    wait_seconds = params.get("wait_seconds", 1)
    if type(wait_seconds) not in (int, float) or not 0 < wait_seconds <= 60:
        invalid("wait_seconds must be finite, positive and at most 60")
    with record_lock(root):
        if resume_latched(root):
            raise Refusal("resume_required", "M1 latch is holding; run a fresh bounded reconciliation")
        state = load_state(local_path(root, "lead-state.json").read_text())
        if state.get("resume_gate", {}).get("status") == "hold":
            raise Refusal("resume_required", "M1 reconciliation is holding; inspect its durable resume plan")
        if state.get("outcome", {}).get("status") == "failed":
            # Ticket 12: a failed mission is terminal; the human decides what happens next.
            raise Refusal("mission_failed",
                          "mission reached a durable failure; inspect " + state["outcome"]["evidence"])
        client = Client(options)
        state["last_turn_at"] = stamp()
        look(client, root, state)
        state["turn"] += 1
        not_run = stop_unreachable_optional(state)
        stalled = stalled_review(root, state)
        candidates = pick(state)
        waiting = next((e for e in state["escalations"] if e["status"] == "waiting"), None)
        if waiting:
            entry = human_turn(root, state, waiting)
        elif any(t["status"] in {"refused", "stopped", "review-refused"}
                 for t in state["tasks"].values() if t.get("required", True)):
            # A failed required task decides the mission; dispatching optional work first only delays that.
            entry = fail_mission(root, state)
        elif candidates and "assign" in candidates[0][2]:
            entry = send_task(client, root, state, state["tasks"][candidates[0][2]["assign"]], options)
        elif candidates:
            ring = candidates[0][2]
            entry = act_ring(root, state, ring)
            if entry["action"] in {"stop", "escalate"}:
                entry["git"] = git_window(state, state["tasks"][ring["task"]])
        elif stalled:
            entry = escalate(root, state, [{"task": stalled["id"], "detail": (
                f"Task {stalled['active']} has an incomplete return, and its owner stayed idle for "
                f"{IDLE_REVIEW_TURNS} turns with the return unchanged.")}], {"moment": "M9", "task": stalled["active"]})
        elif all(t["status"] == "accepted" for t in state["tasks"].values() if t.get("required", True)):
            entry = close_mission(root, state)
        elif blocked := dead_dependency(state):
            task, dep = blocked
            if task.get("dependency_escalated"):
                entry = fail_mission(root, state, [f"Task {task['active']} waits on {dep['active']} "
                                                   f"({dep['status']}); continue cannot accept it"])
            else:
                task["dependency_escalated"] = dep["id"]
                entry = escalate(root, state, [{"task": task["id"], "detail": (
                    f"Task {task['id']} depends on {dep['id']}, which ended {dep['status']} without acceptance. "
                    "Continue cannot accept a stopped dependency, so continue or stop fails the mission; "
                    "reconcile with a new authorized mission.")}], {"moment": "M9", "task": task["active"]})
        else:
            entry = {"moment": "M3", "action": "wait", "reason": "no authorized actionable moment"}
        if not_run:
            entry["not_run"] = not_run
        entry["candidates"] = [{"priority": p, "value": v, **c} for p, v, c in candidates]
        entry["turn"] = state["turn"]
        record(root, state, entry)
        try:
            result = watch(client, {"workspace_id": state["workspace_id"], "duration_seconds": wait_seconds})
        except Refusal as error:
            # The entry is already durable; refusing now would report a recorded action as not taken.
            return {**entry, "wait": {"error": f"{error.code}: {error}"}}
        state["last_watch"] = result
        record(root, state)
        return {**entry, "wait": result["stats"]}


def evidence_binding(root, value):
    """The stored evidence path and the sha256 of the bytes it holds now."""
    resolved = resolve_evidence(root, value)
    if not within(resolved, evidence_roots(root)):
        raise Refusal("path_outside_record", "evidence must stay inside the record or its parent directory")
    if not resolved.is_file():
        raise Refusal("evidence_unavailable", "evidence must be an existing regular file")
    try:
        digest = BoundedReader(max_reads=1, confine=evidence_roots(root)).digest(resolved)
    except OSError as error:
        raise Refusal("evidence_unavailable", f"evidence must be a readable file of at most 2 MiB: {error}") from error
    return (str(resolved.relative_to(root)) if root in resolved.parents else str(resolved)), digest


def record_identity(params):
    required = {"record_root", "task", "attempt", "by", "kind", "identity", "evidence"}
    object_fields(params, required, required)
    root = Path(identifier(params["record_root"], "record_root")).resolve()
    for key in ("task", "attempt", "evidence"):
        identifier(params[key], key)
    if params["by"] not in {"lead", "human"}:
        invalid("by must be lead or human")
    if params["kind"] not in IDENTITY_KINDS:
        invalid("kind must be reviewed, installed or bounded")
    if not isinstance(params["identity"], str) or not re.fullmatch(r"[0-9a-f]{64}|[0-9a-f]{40}", params["identity"]):
        invalid("identity must be a lowercase sha256 or commit digest")
    with record_lock(root):
        state = load_state(local_path(root, "lead-state.json").read_text())
        task = state["tasks"].get(params["task"])
        if task is None:
            raise Refusal("unknown_task", "no task " + params["task"])
        if not re.fullmatch(re.escape(task["id"]) + r"(\.[0-9]+)?", params["attempt"]):
            raise Refusal("attempt_mismatch", f"attempt {params['attempt']} does not belong to task {task['id']}")
        known = attempts_of(state, task)
        if params["attempt"] not in known:
            raise Refusal("unknown_attempt", f"task {task['id']} has no attempt {params['attempt']} "
                          f"(known: {', '.join(known)})")
        evidence, digest = evidence_binding(root, params["evidence"])
        entry = {"kind": params["kind"], "attempt": params["attempt"], "by": params["by"],
                 "identity": params["identity"], "evidence": evidence, "evidence_sha256": digest}
        stored = task.setdefault("identities", [])
        if any({k: row.get(k) for k in entry} == entry for row in stored):
            return {"action": "already-recorded", "task": task["id"], "kind": entry["kind"]}
        stored.append({**entry, "at": stamp()})
        record(root, state, {"moment": "M5", "action": "record-identity", "task": entry["attempt"],
                             "member": entry["by"], "reason": f"{entry['kind']} identity {entry['identity'][:12]}",
                             "evidence": entry["evidence"]})
    return {"action": "identity-recorded", "task": task["id"], "attempt": entry["attempt"],
            "kind": entry["kind"], "identity": entry["identity"]}


def handle(payload, options):
    object_fields(payload, {"command", "params"}, {"command", "params"})
    if payload["command"] == "init":
        return init(payload["params"])
    if payload["command"] == "lead":
        return turn(payload["params"], options)
    if payload["command"] == "answer":
        return answer(payload["params"])
    if payload["command"] == "record":
        return record_identity(payload["params"])
    raise Refusal("unknown_command", "expected init, lead, answer, or record")


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
        if any(not math.isfinite(getattr(options, k)) or getattr(options, k) <= 0
               for k in ("idle_seconds", "read_gap_seconds")) or not 500 <= options.shell_ready_ms <= 2500:
            invalid("invalid guard timings")
        result = handle(json_loads(sys.stdin.read()), options)
        print(json.dumps({"ok": True, "result": result}, allow_nan=False))
        return 0
    except (Refusal, OSError, ValueError, compliance.UsageError) as error:
        print(json.dumps({"ok": False, "error": {
            "code": getattr(error, "code", "invalid_input"), "message": str(error),
        }}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
