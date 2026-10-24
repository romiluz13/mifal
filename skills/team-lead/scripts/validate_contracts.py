#!/usr/bin/env python3
"""Validate the team-lead fleet contracts: doorbell lines, briefs, receipts.

Stdlib only. The shapes enforced here are defined in
references/contracts/ (ADR-0002); fixtures for the selfcheck live in
scripts/fixtures/.

Usage:
  validate_contracts.py doorbell [--parse] "DONE 7 .team/tasks/7.md"
  validate_contracts.py brief path/to/task.md
  validate_contracts.py receipt path/to/return.md
  validate_contracts.py brief path/to/task.md --matt
  validate_contracts.py workflow path/to/state.md --gate entry
  validate_contracts.py read path/to/SKILL.md
  validate_contracts.py selfcheck

Exit codes: 0 valid, 1 invalid, 2 usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DOORBELL_TYPES = ("DONE", "HELP", "HELD", "STOPPED")

TASK_ID = r"[0-9]+(?:\.[0-9]+)?"
TASK_ID_RE = re.compile(r"^" + TASK_ID + r"$")

LATITUDES = {
    "look": "look",
    "propose": "propose",
    "do & tell": "do-tell",
    "do and tell": "do-tell",
    "do-tell": "do-tell",
    "own": "own",
}

REQUIRED_BRIEF_FIELDS = ("task", "owner", "latitude", "return")
REQUIRED_BRIEF_SECTIONS = ("Why", "Outcome", "Done means", "Stop rule")
REQUIRED_RECEIPT_SECTIONS = ("Result", "Claims", "Evidence")

DONE_PAYLOAD_HINT = "an artifact path"
PAYLOAD_HINTS = {
    "DONE": DONE_PAYLOAD_HINT,
    "HELP": "the reason",
    "HELD": "what it waits on",
    "STOPPED": "why it stopped",
}


# These are local contract minima, not Ask Matt's semantic branch graph.
ROUTE_PHASES = {
    "research": {"scope", "source", "investigate", "synthesize", "review", "verify", "report"},
    "plan": {"scope", "inspect", "context", "research", "resolve", "plan", "review", "verify", "deliver", "report"},
    "build": {"scope", "research", "context", "plan", "implement", "implementation", "review", "remediate", "verify", "retro", "report"},
    "debug": {"scope", "reproduce", "research", "context", "hypothesis", "plan", "diagnose", "fix", "review", "regression", "verify", "retro", "report"},
    "review": {"fix", "base", "scope", "inspect", "context", "review", "substantiate", "verify", "report"},
}
# The plan route's phases from resolving design decisions onward, where grilling evidence is due.
PLAN_GRILLING_PHASES = {"resolve", "plan", "review", "verify", "deliver", "report"}
DDD_PHASE_SKILL = {
    **dict.fromkeys(("research", "context", "source", "investigate", "inspect", "reproduce"), "ddd-scope"),
    **dict.fromkeys(("plan", "resolve", "hypothesis"), "ddd-ground"),
    **dict.fromkeys(("review", "verify", "regression", "substantiate", "retro", "report", "deliver"), "ddd-verify"),
}


# ---------------------------------------------------------------- doorbell

def parse_doorbell(line: str):
    """Parse one doorbell line. Return (record, errors); record is None on error."""
    text = line.strip()
    if not text:
        return None, [
            "empty doorbell; expected '<TYPE> <task> <payload>', "
            "e.g. 'DONE 7 .team/tasks/7.md'"
        ]
    parts = text.split(None, 2)
    dtype = parts[0]
    if dtype not in DOORBELL_TYPES:
        return None, [
            f"unknown doorbell type '{dtype}'; "
            f"expected one of {', '.join(DOORBELL_TYPES)}"
        ]
    if len(parts) < 2:
        return None, [
            f"missing task id; expected '{dtype} <task> <payload>'"
        ]
    task_token = parts[1]
    if not TASK_ID_RE.match(task_token):
        return None, [
            f"bad task id '{task_token}'; use a stable task id ('7') "
            f"or an attempt id ('7.2')"
        ]
    if len(parts) < 3 or not parts[2].strip():
        return None, [
            f"{dtype} needs {PAYLOAD_HINTS[dtype]} after the task id; "
            f"e.g. '{dtype} {task_token} ...'"
        ]
    payload = parts[2].strip()
    if "\n" in payload:
        return None, [
            "doorbell payload must be one line; the doorbell is a single "
            "line — the detail lives in the record, not the pane"
        ]
    if dtype == "DONE" and len(payload.split()) != 1:
        return None, [
            f"DONE payload must be a single artifact path (no spaces); got "
            f"'{payload}'. Put prose in the return file and ring "
            f"'DONE {task_token} <path>'."
        ]
    task, dot, attempt = task_token.partition(".")
    record = {
        "type": dtype,
        "task": task,
        "attempt": task_token if dot else None,
    }
    if dtype == "DONE":
        record["artifact"] = payload
    else:
        record["detail"] = payload
    return record, []


# ---------------------------------------------------------------- markdown

def parse_frontmatter(text: str):
    """Parse minimal 'key: value' frontmatter. Return (fields, body, errors)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text, [
            "missing frontmatter; start the file with a '---' block holding "
            "task, owner, latitude, and return, e.g.:\n"
            "  ---\n  task: 7\n  owner: kai\n  latitude: do-tell\n"
            "  return: .team/tasks/7.md\n  ---"
        ]
    fields = {}
    errors = []
    end = None
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            end = i
            break
        if not line.strip():
            continue
        m = re.match(r"^([a-z][a-z0-9_-]*):\s*(.*)$", line)
        if not m:
            errors.append(
                f"frontmatter line {i + 1}: '{line}' is not 'key: value'; "
                f"use plain lowercase scalar keys (no lists or nesting)"
            )
            continue
        # Strip trailing '# ...' comments so the contract's own annotated
        # template ('attempt: 7.2        # only on corrections') validates.
        value = re.sub(r"\s+#.*$", "", m.group(2)).strip()
        fields[m.group(1)] = value
    if end is None:
        return None, text, ["frontmatter never closes; add a closing '---' line"]
    body = "\n".join(lines[end + 1:])
    if errors:
        return None, body, errors
    return fields, body, []


def sections(body: str, level: int):
    """Return ordered [(heading, text)] for headings at the given '#' level."""
    marker = "#" * level
    pat = re.compile(r"^" + marker + r"\s+(.+?)\s*$")
    out = []
    current = None
    buf: list[str] = []
    for line in body.splitlines():
        m = pat.match(line)
        if m and not line.startswith(marker + "#"):
            if current is not None:
                out.append((current, "\n".join(buf)))
            current = m.group(1)
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        out.append((current, "\n".join(buf)))
    return out


def find_section(secs, name):
    for heading, text in secs:
        if heading.lower().startswith(name.lower()):
            return text
    return None


# ---------------------------------------------------------------- brief

def validate_workflow(text: str, path: Path, gate="entry", require_loads=True, receipt=False,
                      read_text=None, body_digest=None):
    read_text = read_text or regular_text
    body_digest = body_digest or workflow_digest
    body = workflow_text(text).split("\n## Return", 1)[0]
    blocks = [b for h, b in sections(body, 2) if h.lower() == "workflow"]
    if len(blocks) > 1:
        return [f"{path}: {len(blocks)} '## Workflow' sections; keep one"]
    if not blocks:
        return [f"{path}: missing '## Workflow' for the Matt check; add one before '## Return', e.g.:\n"
                "  ## Workflow\n  Methodology: matt\n  Executor: kai\n  Route: build\n  Phase: implement\n"
                "  Next gate: the slice's tests pass\n  Start: <full 40-character commit SHA>\n"
                "  DDD: n/a: no vendor behaviour in scope\n  UX: n/a: no user-facing change\n"
                "  Procedure: ~/.agents/skills/engineering-workflow/SKILL.md\n"
                "  Procedure: ~/.agents/skills/ask-matt/SKILL.md\n"
                "  Loaded: ~/.agents/skills/ask-matt/SKILL.md | kai: sha256:<digest> <where you loaded it>\n"
                "Executor is the brief's owner; `validate_contracts.py read <path>` prints a body's digest. "
                "The rerun names anything still missing; the full template is in "
                "engineering-workflow/references/phase-record.md."]
    fields = {}
    errors = []
    repeated = {"procedure": [], "loaded": [], "check": [], "cut": []}
    for line in blocks[0].splitlines():
        m = re.match(r"^\s*(?:- )?([A-Za-z][A-Za-z -]*):\s*(.*)$", line)
        if not m:
            continue
        key, value = m.group(1).lower(), m.group(2).strip()
        if key in ("procedures", "required skill paths"):
            repeated["procedure"].extend(v.strip() for v in value.split(","))
        elif key in repeated:
            repeated[key].append(value)
        elif key in {"methodology", "executor", "route", "phase", "next gate",
                     "start", "ddd", "ux", "state", "snapshot", "scheduler",
                     "integration owner", "implement", "grilling", "route decision", "retro"}:
            if key in fields:
                errors.append(f"duplicate Workflow field '{key}'")
            fields[key] = value
        else:
            errors.append(f"unknown Workflow field '{key}'; keep prose outside this section")
    for key in ("Methodology", "Executor", "Route", "Phase", "Next gate", "Start", "DDD", "UX"):
        if not workflow_value(fields.get(key.lower(), "")):
            errors.append(f"missing or placeholder Workflow {key}" + placeholder_note(f"{key}: {fields.get(key.lower(), '')}"))
    if fields.get("methodology", "").lower() != "matt":
        errors.append("Methodology must be matt; this check cannot change another owner")
    identity, _, identity_errors = parse_frontmatter(text)
    if not identity_errors and identity.get("owner") != fields.get("executor"):
        errors.append("Executor must match the brief's owner")
    route = fields.get("route", "").lower()
    if route not in ("research", "plan", "build", "debug", "review"):
        errors.append("Route must be research, plan, build, debug or review")
    phase_match = re.match(r"\s*([a-z]+)", fields.get("phase", "").lower())
    phase = phase_match.group(1) if phase_match else ""
    if route in ROUTE_PHASES and phase not in ROUTE_PHASES[route]:
        errors.append(f"Phase must start with a {route} phase: {', '.join(sorted(ROUTE_PHASES[route]))}")
    start = fields.get("start", "")
    fixed = re.fullmatch(r"(?:[0-9a-f]{40}|sha256:[0-9a-f]{64})", start, re.I)
    no_code = re.fullmatch(r"none:\s*(.+)", start, re.I)
    if not fixed and not (route in ("research", "plan") and no_code
                          and workflow_value(no_code.group(1))):
        errors.append("Start needs a full commit SHA or sha256:<digest>; moving refs cannot pin work"
                      + (placeholder_note(no_code.group(1)) if route in ("research", "plan") and no_code else ""))
    for key in ("ddd", "ux"):
        disposition = re.fullmatch(r"(applies|n/a):\s*(.+)", fields.get(key, ""), re.I)
        if not disposition or not workflow_value(disposition.group(2)):
            errors.append(f"{key.upper()} needs 'applies: <trigger>' or 'n/a: <reason>'"
                          + (placeholder_note(f"{key.upper()}: {fields[key]}") if disposition else ""))
    procedures = []
    for value in repeated["procedure"]:
        if not workflow_value(value):
            errors.append("Procedure needs an available body path" + placeholder_note(value))
            continue
        procedure = workflow_path(value, path).resolve()
        if not procedure.is_file():
            errors.append(f"Procedure file unavailable: {value}")
        procedures.append(procedure)
    pool = Path.home() / ".agents" / "skills"
    errors.extend(workflow_map_errors(pool, read_text))
    map_path = pool.joinpath(*WORKFLOW_MAP)
    try:
        map_text = workflow_text(read_text(map_path))
        map_steps, map_phases = workflow_map_steps(map_text)[0], workflow_map_phases(map_text)
    except (OSError, UnicodeError):
        map_steps, map_phases = {}, {}
    # A receipt honours the same verified Cut as the gates: the brief's own (before its Return) or the parent State's.
    decided = fields.get("route decision") or next(
        iter(inherited_workflow_lines(fields, path, read_text, "route decision")), "")
    parent_record = workflow_path(fields["state"].split("#", 1)[0], path) if fields.get("state") else path
    cut, cut_problems = cut_errors(
        [(v, path) for v in repeated["cut"]]
        + [(v, parent_record) for v in inherited_workflow_lines(fields, path, read_text, "cut")],
        record_steps(map_steps, route, strip_stamp(decided)), read_text)
    errors.extend(cut_problems)
    if (pool / "ask-matt" / "SKILL.md").resolve() not in procedures:
        errors.append("Procedure must include the canonical Ask Matt SKILL.md routing body")
    if (pool / "engineering-workflow" / "SKILL.md").resolve() not in procedures:
        errors.append("Procedure must include the current Engineering Workflow SKILL.md")
    exemption = re.fullmatch(r"n/a:\s*(docs-only|coordination):\s*(.+)", fields.get("implement", ""), re.I)
    if fields.get("implement") and not (exemption and workflow_value(exemption.group(2))):
        errors.append("Implement needs 'n/a: docs-only: <reason>' or 'n/a: coordination: <reason>'"
                      + (placeholder_note(exemption.group(2)) if exemption else ""))
        exemption = None
    required = []
    diagnosis_only = re.fullmatch(r"n/a:\s*diagnosis-only:\s*(.+)", fields.get("retro", ""), re.I)
    if fields.get("retro", "").lower().startswith("n/a:") and not (
            route == "debug" and diagnosis_only and workflow_value(diagnosis_only.group(1)) and phase != "fix"):
        errors.append("Retro exemption is only 'n/a: diagnosis-only: <reason>' for debug work that made no fix"
                      + (placeholder_note(diagnosis_only.group(1))
                         if route == "debug" and diagnosis_only and phase != "fix" else ""))
        diagnosis_only = None
    retro_required = (route in {"build", "debug"} and gate == "accept" and not receipt and not diagnosis_only
                      and "retro" not in cut)
    if phase == "retro" or retro_required:
        required.extend(("retro", "writing-for-agents"))
    if retro_required or (phase == "retro" and fields.get("retro")):
        _, evidence_errors, _ = workflow_evidence(
            fields.get("retro", ""), path, read_text, "Retro", ("Sources", "Findings"))
        errors.extend(evidence_errors)
    grilling = re.fullmatch(r"(interview|accepted):\s*(.+)", fields.get("grilling", ""), re.I)
    grilling_needed = (route == "build" and "grilling" not in cut) or (
        route == "debug" and (phase == "fix" or retro_required))
    if (route == "plan" and phase in PLAN_GRILLING_PHASES and not receipt and not fields.get("grilling")
            and "resolve" not in cut):
        errors.append(f"A plan record at resolve or later needs a Grilling line, and phase '{phase}' has none: record "
                      "'interview: <unsettled decisions>' while grilling or 'accepted: sha256:<digest> | <scope/decisions artifact>'")
    elif grilling_needed or fields.get("grilling"):
        if not grilling or not workflow_value(grilling.group(2)):
            errors.append("Grilling needs 'interview: <reason>' or 'accepted: sha256:<digest> | <scope/decisions artifact>'"
                          + (placeholder_note(grilling.group(2)) if grilling else ""))
        elif grilling.group(1).lower() == "accepted":
            accepted, evidence_errors, raw = workflow_evidence(
                grilling.group(2), path, read_text, "Grilling", ("Accepted scope", "Design decisions"))
            errors.extend(evidence_errors)
            scope = find_section(sections(accepted, 2), "Accepted scope") or ""
            approvals = re.findall(r"(?mi)^Accepted:\s*(.+)$", scope)
            if len(approvals) != 1 or not workflow_value(approvals[0]):
                errors.append("Grilling evidence needs one Accepted: <actual approval or accepted-ticket source> in Accepted scope"
                              + (placeholder_note(approvals[0]) if len(approvals) == 1 else ""))
            elif not receipt and not quote_has_source(approvals[0]):
                errors.append("Grilling evidence's Accepted: needs the human's quote and a source pointer "
                              "('Accepted: <quote> | <source>'); the quote covers scope only")
            described = re.sub(r"(?mi)^Accepted:.*$", "", scope).strip()
            if not workflow_value(described):
                errors.append("Grilling evidence must describe the accepted work, not only name an approval"
                              + placeholder_note(described))
            pointer = re.fullmatch(r"sha256:[0-9a-f]{64}\s*\|\s*(.+)", grilling.group(2), re.I)
            if accepted and pointer and not receipt:
                errors.extend(griller_errors(accepted, raw, workflow_path(pointer.group(1).strip(), path),
                                             *parent_executors(fields, path, read_text), read_text, body_digest))
        elif phase in {"implement", "implementation", "remediate", "fix", "review", "verify", "deliver", "report"} or gate in {"review", "accept"}:
            errors.append("Grilling interview is unfinished; accepted scope/design evidence is required before implementation")
        elif phase in {"plan", "resolve"}:
            wrapper = "grill-with-docs" if (pool / "grill-with-docs" / "SKILL.md").resolve() in procedures else "grill-me"
            required.extend((wrapper, "grilling"))
            if wrapper == "grill-with-docs":
                required.append("domain-modeling")
    producers = {name for name in ("to-spec", "to-tickets") if (pool / name / "SKILL.md").resolve() in procedures}
    if route == "plan" and producers and phase not in PLAN_GRILLING_PHASES and not receipt:
        errors.append(f"A plan record at phase '{phase}' selects {' and '.join(sorted(producers))}, but a spec or "
                      "ticket producer runs after resolve: move the producer to a phase at resolve or later")
    if (fields.get("route decision") or producers) and not receipt:
        errors.extend(route_decision_errors(strip_stamp(fields.get("route decision", "")), path, route, phase, gate, producers,
                                            bool(grilling) and grilling.group(1).lower() == "accepted", read_text,
                                            waived={"spec", "tickets"} & cut))
    if fields.get("route decision") and not receipt:
        errors.extend(route_decision_order_errors(
            fields["route decision"], inherited_workflow_lines(fields, path, read_text, "route decision"),
            repeated["check"]))
    if exemption and exemption.group(1).lower() == "coordination":
        required.append("team-lead")
    if route == "build" and phase in {"implement", "implementation", "remediate"} and not exemption and "implement" not in cut:
        required.extend(("implement", "tdd"))
    if route == "debug" and phase in {"reproduce", "hypothesis", "diagnose", "fix"}:
        required.append("diagnosing-bugs")
    if route == "debug" and phase == "fix" and not exemption and "implement" not in cut:
        required.append("tdd")
    if route == "review" or (route in {"build", "debug"} and (phase == "review" or gate in {"review", "accept"})
                             and "review" not in cut):
        required.append("code-review")
    for name in required:
        if (pool / name / "SKILL.md").resolve() not in procedures:
            errors.append(f"Phase '{phase}' needs {name} SKILL.md in Procedure/Loaded")
    if require_loads:
        load_values = repeated["loaded"]
        checks = list(repeated["check"])
        if receipt:
            _, portion = split_returns(text)[-1]
            checks += re.findall(r"(?mi)^\s*(?:- )?Check:\s*(.+)$", workflow_text(portion))
            if not identity_errors:
                current = identity.get("attempt") or identity.get("task")
                if current not in CLOSES_LINE_RE.findall(portion):
                    errors.append("latest read records must close the current task/attempt")
            load_values = re.findall(r"(?mi)^\s*(?:- )?Loaded:\s*(.+)$", workflow_text(portion))
            claim_sections = [b for h, b in sections(workflow_text(portion), 3) if h.lower().startswith("claims")]
            if len(claim_sections) != 1:
                errors.append("latest return needs exactly one Claims section")
            claims = claim_sections[0] if len(claim_sections) == 1 else ""
            reported = [m["claim"].strip() for m in (CLAIM_RE.match(line.strip()) for line in claims.splitlines()) if m]
            declared = [claim for claim, _, _ in workflow_claims(body)]
            for claim in sorted(set(reported) - set(declared)):
                errors.append(f"latest return reports claim '{claim}' absent from Done means")
            for claim in declared:
                if claim not in reported:
                    errors.append(f"latest return has no status for Done means claim '{claim}'")
                elif reported.count(claim) > 1:
                    errors.append(f"latest return has duplicate statuses for claim '{claim}'")
        loads, stale = set(), []
        executor = fields.get("executor", "") + ":"
        for value in load_values:
            target, separator, evidence = value.partition("|")
            evidence = evidence.strip()
            proof = re.fullmatch(r"sha256:([0-9a-f]{64})\s+(?:bytes:([0-9]+)\s+)?(.+)",
                                 evidence[len(executor):].strip(), re.I)
            if (not separator or not workflow_value(target.strip())
                    or not evidence.startswith(executor)
                    or not proof or not workflow_value(proof.group(3))):
                errors.append("Loaded needs '<body path> | <executor>: sha256:<body digest> [bytes:<n>] <read pointer>'"
                              + placeholder_note(target.strip(), proof.group(3) if proof else ""))
            elif proof.group(3).lower().startswith("bytes:"):
                errors.append("Loaded byte count must be a nonnegative integer followed by a read pointer")
            elif re.search(r"(?i)^(?:partial|truncated|excerpt|snippet|metadata[- ]only|description[- ]only|frontmatter[- ]only)\b|\bcoverage:\s*(?:partial|truncated)\b", proof.group(3)):
                errors.append(f"Loaded declares a partial read of {target.strip()}; load the complete body before work")
            else:
                loaded_path = workflow_path(target.strip(), path).resolve()
                if loaded_path in procedures:
                    try:
                        data = read_text(loaded_path).encode("utf-8") if proof.group(2) else None
                        digest = hashlib.sha256(data).hexdigest() if data is not None else body_digest(loaded_path)
                        if digest != proof.group(1).lower():
                            stale.append(loaded_path)
                        elif data is not None and len(data) != int(proof.group(2)):
                            errors.append(f"Loaded byte count differs from {loaded_path}; record the complete read")
                        else:
                            loads.add(loaded_path)
                    except OSError as e:
                        errors.append(f"Loaded body cannot be checked: {e}")
        # A reload adds a matching line beside the original, which stays: a stale line is an error only when no
        # line of this record (same resolved path, same executor, complete read) matches the current body.
        for loaded_path in dict.fromkeys(stale):
            if loaded_path not in loads:
                errors.append(f"Loaded body changed: {loaded_path}; reload before proceeding")
        for procedure in procedures:
            if procedure not in loads:
                errors.append(f"missing Loaded read record for {procedure}")
        errors.extend(late_read_errors(load_values, checks, phase, map_phases, valid_start_steps(map_steps), record=path, pool=pool))
    if fields.get("ux", "").lower().startswith("applies:") and (
            pool / "team-lead" / "references" / "ux-acceptance.md").resolve() not in procedures:
        errors.append("UX applies: include the planning/acceptance reference in Procedure/Loaded")
    if fields.get("ddd", "").lower().startswith("applies:"):
        ddd_required = ["ddd"] + ([DDD_PHASE_SKILL[phase]] if phase in DDD_PHASE_SKILL else [])
        for name in ddd_required:
            if (pool / name / "SKILL.md").resolve() not in procedures:
                errors.append(f"DDD applies in phase '{phase}': include {name} SKILL.md in Procedure/Loaded")
    state = body
    if fields.get("state"):
        state_path = workflow_path(fields["state"].split("#", 1)[0], path)
        try:
            state = workflow_text(read_text(state_path))
        except (OSError, UnicodeError) as e:
            errors.append(f"cannot read State checklist: {e}")
            state = ""
    checklist = [b for h, b in sections(state, 2) if h.lower() == "phase checklist"]
    if len(checklist) != 1 or not re.search(r"(?m)^\s*- \[[ xX]\]\s+\S", checklist[0]):
        errors.append("State needs one '## Phase checklist' with ordered task items")
    if len(checklist) == 1 and any(
            marker_line(line) and not CHECKBOX_RE.match(line) for line in checklist[0].splitlines()):
        errors.append("Phase checklist has a malformed task item; every marker line must be exactly "
                      "'- [ ] <phase>' or '- [x] <phase>' ('*', '+', numbered and unspaced markers are refused)")
    own = [b for h, b in sections(body, 2) if h.lower() == "phase checklist"]
    if not receipt and len(own) == 1:
        # Only the record's own checklist is held to its own route; a parent State's checklist is the parent's, and
        # the parent's gates hold it to the parent's route. A worker with no checklist of its own gets no step check.
        decisions = ([fields["route decision"]] if fields.get("route decision")
                     else inherited_workflow_lines(fields, path, read_text, "route decision"))
        errors.extend(required_step_errors(
            map_steps, route, strip_stamp(decisions[0]) if decisions else None, phase, gate,
            re.findall(r"(?m)^\s*- \[([ xX])\]\s+(.+)$", own[0]), cut, map_path))
    if gate == "accept" and not receipt and len(checklist) == 1:
        items = re.findall(r"(?m)^\s*- \[([ xX])\]\s+(.+)$", checklist[0])
        unfinished = [(i, label) for i, (mark, label) in enumerate(items) if mark == " "]
        report_only = (len(unfinished) == 1 and unfinished[0][0] == len(items) - 1
                       and unfinished[0][1].strip() == "Report")
        if unfinished and not report_only:
            errors.append(f"Accept holds unfinished Phase checklist work: '- [ ] {unfinished[0][1].strip()[:60]}'; "
                          "only the final item may remain open, and it must be exactly '- [ ] Report'. "
                          "Put the delivery description in Next gate, e.g. change '- [ ] Report: <text>' to '- [ ] Report'")
    if gate == "review" or (gate == "accept" and route in ("build", "debug", "review")):
        if not workflow_value(fields.get("snapshot", "")):
            errors.append("Snapshot is required before review or acceptance of code work"
                          + placeholder_note(fields.get("snapshot", "")))
        else:
            errors.extend(workflow_snapshot(fields["snapshot"], path, body_digest, read_text,
                                            guard=route in ("build", "debug") and not diagnosis_only))
    elif gate == "accept" and fields.get("snapshot"):
        errors.extend(workflow_snapshot(fields["snapshot"], path, body_digest))
    if gate == "accept":
        if not repeated["check"]:
            errors.append("Check needs at least one required final claim with passed evidence")
        checked_claims = set()
        for value in repeated["check"]:
            parts = [p.strip() for p in value.split("|", 2)]
            if len(parts) != 3 or not workflow_value(parts[0]) or parts[1] != "passed" or not workflow_value(parts[2]):
                errors.append("Check needs '<required claim> | passed | <final-identity evidence>'; failed/untested stays held"
                              + (placeholder_note(value) if len(parts) == 3 and parts[1] == "passed" else ""))
            else:
                checked_claims.add(parts[0])
        if retro_required and "retro" not in checked_claims:
            errors.append("Check needs 'retro | passed | <session review evidence>' before whole-task completion")
        required_claims = workflow_claims(state) + (workflow_claims(body) if fields.get("state") else [])
        for claim, _, _ in required_claims:
            if claim not in checked_claims:
                errors.append(f"missing passed Check for declared Done means claim '{claim}'")
    claim_sources = []
    if gate == "accept" and not receipt:
        claim_sources.append(state)
        if fields.get("state") and any(h.lower().startswith("done means") for h, _ in sections(body, 2)):
            claim_sources.append(body)
    elif receipt or not require_loads:
        claim_sources.append(body)
    for source in claim_sources:
        done_sections = [b for h, b in sections(source, 2) if h.lower().startswith("done means")]
        if len(done_sections) != 1:
            errors.append("Matt needs exactly one active Done means section per requirement surface")
        for done in done_sections:
            for line in done.splitlines():
                if marker_line(line) and not line.strip().startswith("- "):
                    errors.append(f"Done means line '{line.strip()[:60]}' is not a claim; "
                                  "every marker line must be '- <claim>: <check>'")
        claims = workflow_claims(source)
        if not claims or any(not sep or not workflow_value(claim)
                             or not workflow_value(check) for claim, sep, check in claims):
            lines = [line.strip() for line in (find_section(sections(source, 2), "Done means") or "").splitlines()
                     if line.strip().startswith("- ")]
            offending = next((line for line, (claim, sep, check) in zip(lines, claims)
                              if re.search(r"<[^>]+>", claim + check)
                              and (not workflow_value(claim) or not workflow_value(check))), "")
            errors.append("Matt Done means needs nonempty named claims and checks" + placeholder_note(offending))
        names = [claim for claim, _, _ in claims]
        if len(set(names)) != len(names):
            errors.append("Matt Done means claim names must be unique")
    return [f"{path}: {e}" for e in errors]


ROUTE_DECISION_FORMS = ("Route decision needs 'multi-session: yes; spec: <path>; tickets: <path>' or "
                        "'multi-session: no; reason: <why no spec and tickets are needed>'")


# Build phases from implementation onward, where the spec and tickets must exist.
BUILD_PHASES_FROM_IMPLEMENT = {"implement", "implementation", "remediate", "review", "verify", "retro", "report"}


def route_decision_errors(value, record, route, phase, gate, producers, grilled, read_text, waived=()):
    """Ask Matt's multi-session branch, recorded: yes names its outputs, no states why.

    Only what the proposed next action needs is checked, read from the phase and the selected
    `producers` (to-spec, to-tickets): the outputs a later producer or implementer will make stay
    unpinned until then. A selected producer is held to its needs whatever the decision says, or
    whether one is recorded. `grilled` is whether the Grilling line is accepted."""
    outputs = {}
    if value:
        branch = re.fullmatch(r"multi-session:[ \t]*(yes|no)[ \t]*(?:;[ \t]*(.*))?", value, re.I)
        if not branch:
            return [f"{ROUTE_DECISION_FORMS}, found '{value[:80]}'"]
        if branch.group(1).lower() == "no":
            reason = re.fullmatch(r"reason:[ \t]*(.*)", branch.group(2) or "", re.I)
            if not reason or not workflow_value(reason.group(1)) or not re.search(r"[^\W_]", reason.group(1)):
                return ["Route decision 'multi-session: no' needs a reason: 'multi-session: no; reason: <why this work "
                        "needs no spec and tickets>'" + (placeholder_note(reason.group(1)) if reason else "")]
        else:
            for clause in (branch.group(2) or "").split(";"):
                named = re.fullmatch(r"(spec|tickets):[ \t]*(\S.*?)[ \t]*", clause.strip(), re.I)
                if named and named.group(1).lower() not in outputs and workflow_value(named.group(2)):
                    outputs[named.group(1).lower()] = named.group(2)
                else:
                    outputs = {}
                    break
            if set(outputs) != {"spec", "tickets"}:
                return [f"{ROUTE_DECISION_FORMS}; 'multi-session: yes' names its spec and its tickets once each, "
                        f"found '{value[:120]}'" + placeholder_note(value)]
    if outputs and route == "build" and (phase in BUILD_PHASES_FROM_IMPLEMENT or gate in {"review", "accept"}):
        action, ready = "implementation", "the pinned spec and tickets exist"
        needed = tuple(name for name in ("spec", "tickets") if name not in waived)
    elif "to-tickets" in producers:
        action, ready, needed = "the ticket producer (to-tickets)", "the pinned spec exists", ("spec",)
    elif "to-spec" in producers:
        action, ready, needed = "the spec producer (to-spec)", "grilling is complete", ()
    else:
        return []
    held = (f"Route decision 'multi-session: yes' holds {action} until" if outputs
            else f"The Procedure list selects {action}, which is held until")
    problems = [] if grilled or action == "implementation" else [
        f"{held} grilling is complete: record 'Grilling: accepted: sha256:<digest> | <scope/decisions artifact>'"]
    for name in needed:
        problem = (decision_output_problem(name, outputs[name], record, read_text) if name in outputs
                   else f"the {name} is not named; record 'Route decision: multi-session: yes; spec: sha256:<digest> | "
                        "<path>; tickets: <path>'")
        if problem:
            problems.append(f"{held} {ready}: {problem}")
    return problems


def decision_output_problem(name, ref, record, read_text):
    """Why a route decision's spec or tickets artifact is not ready, or None when it is pinned and unchanged."""
    label, be = ("the spec", "is") if name == "spec" else ("the tickets", "are")
    pin = re.fullmatch(r"sha256:([0-9a-f]{64})[ \t]*\|[ \t]*(\S.*)", ref, re.I)
    if not pin:
        return f"{label} {be} unpinned; name it '{name}: sha256:<digest> | <path>'"
    target = workflow_path(pin.group(2).strip(), record)
    try:
        text = read_text(target)
    except (OSError, UnicodeError) as e:
        return f"{label} {be} unavailable at {target} ({e})"
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != pin.group(1).lower():
        return f"{label} changed since the decision pinned it ({target}); reconcile it before proceeding"
    if not text.strip():
        return f"{label} {be} empty ({target})"
    return None


def quote_has_source(value):
    """`Accepted: <quote> | <source pointer>`: both halves present and not placeholders."""
    quote, bar, source = value.strip().rpartition(" | ")
    return bool(bar) and workflow_value(quote) and workflow_value(source)


def design_parts(text):
    """(digest, unclosed): the sha256 over a plan's design decisions and whether a comment or fence left open inside
    one makes its end unreadable. The digest covers every '## Design decisions*' section (heading and lines) with each
    visible `Griller:` line removed, so the griller's own pin cannot make the hash circular. Line endings and trailing
    whitespace are normalised and a section's closing blank lines dropped; everything else, fenced and commented text
    included, stays significant. The digest is None when the text has no such section."""
    rows, unclosed, opened = scan_markdown(text)
    blocks, block, inside = [], None, set()
    for number, row in enumerate(rows):
        line = row.line.rstrip(" \t")
        if not row.fenced and not row.in_comment:
            heading = re.match(r"^##\s+(.+?)\s*$", line)
            if heading and not line.startswith("###"):
                block = [] if heading.group(1).lower().startswith("design decisions") else None
                if block is not None:
                    blocks.append(block)
        if block is not None:
            inside.add(number)
            if row.fenced or row.in_comment or not re.match(r"(?i)Griller:", line):
                block.append(line)
    if not blocks:
        return None, False
    lines = []
    for block in blocks:
        while block and not block[-1]:
            block.pop()
        lines.extend(block)
    digest = hashlib.sha256(("".join(line + "\n" for line in lines)).encode("utf-8")).hexdigest()
    return digest, unclosed is not None and opened in inside


def design_digest(text):
    return design_parts(text)[0]


def griller_errors(accepted, raw, evidence, executors, parent_problem, read_text, body_digest):
    """Accepted means grilled by someone else: the design decisions must name a griller task that holds up."""
    design = "\n".join(block for heading, block in sections(accepted, 2) if heading.lower().startswith("design decisions"))
    named = re.findall(r"(?mi)^Griller:[ \t]*(\S.*)$", design)
    if not named:
        return ["Grilling evidence needs a Griller: line in Design decisions: accepted means grilled by an agent "
                "other than the executor, and a plan only the lead wrote names none"]
    problems = [parent_problem] if parent_problem else []
    ours, ambiguous = design_parts(raw)
    if ambiguous:
        problems.append("Grilling evidence: " + UNCLOSED_MESSAGE.format(evidence))
    if re.search(r"(?mi)^[ \t]*(?:(?:[-*+]|\d+[.)])[ \t]+)?Accepted:", design):
        problems.append("Grilling evidence puts an Accepted: line in Design decisions; the human's quote covers "
                        "scope only, so design decisions rest on a Griller:")
    unmet = []
    for value in named:
        found = griller_task_errors(value.strip(), evidence, ours, executors, read_text, body_digest)
        if not found:
            return problems
        unmet.extend(found)
    return problems + unmet


def griller_task_errors(value, evidence, ours, executors, read_text, body_digest):
    pin = re.fullmatch(r"sha256:([0-9a-f]{64})\s*\|\s*(.+)", value, re.I)
    if not pin:
        return [f"Griller needs 'sha256:<digest> | <griller task file>', found '{value[:80]}'"]
    target = workflow_path(pin.group(2).strip(), evidence)
    try:
        text = read_text(target)
    except (OSError, UnicodeError) as e:
        return [f"Griller task {target} unavailable: {e}"]
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != pin.group(1).lower():
        return [f"Griller task {target} changed since the evidence pinned it; reconcile it before proceeding"]
    problems = []
    try:
        invalid = (validate_receipt(text, str(target)) + validate_brief(text, str(target))
                   + validate_workflow(text, target, "entry", require_loads=True, receipt=True,
                                       read_text=read_text, body_digest=body_digest))
    except (OSError, ValueError) as e:
        invalid = [f"invalid Workflow record: {e}"]
    if invalid:
        problems.append(f"Griller task {target} receipt does not validate (receipt --matt): " + "; ".join(invalid))
    grilling = (Path.home() / ".agents" / "skills" / "grilling" / "SKILL.md").resolve()
    if grilling not in workflow_procedure_paths(text, target):
        problems.append(f"Griller task {target} has no grilling read record: it must list {grilling} as a "
                        "Procedure and record the complete read in its latest return")
    portion = split_returns(text)[-1][1]
    latest = visible(portion)
    if scan_markdown(portion)[1]:
        problems.append(f"Griller task {target}: " + UNCLOSED_MESSAGE.format(target))
    stated = re.findall(r"(?mi)^Frontier:[ \t]*(.*?)[ \t]*$", latest)
    if [line.lower() for line in stated] != ["empty"]:
        found = "none" if not stated else f"'Frontier: {stated[0]}'" if len(stated) == 1 else f"{len(stated)} lines"
        problems.append(f"Griller task {target} does not return an empty frontier: its latest return needs "
                        f"exactly one 'Frontier: empty' line, found {found}")
    problems.extend(griller_binding_errors(target, latest, evidence, ours))
    unpassed = [f"{m['claim'].strip()}: {m['status']}" for body in
                (b for h, b in sections(latest, 3) if h.lower().startswith("claims"))
                for m in (CLAIM_RE.match(line.strip()) for line in body.splitlines()) if m and m["status"] != "passed"]
    if unpassed:
        problems.append(f"Griller task {target}: the griller's return reports a failed or untested claim "
                        f"({'; '.join(unpassed)}); a griller that did not pass its own claims has not grilled the plan")
    fields, _, _ = parse_frontmatter(text)
    owner = (fields or {}).get("owner", "")
    if owner.strip().casefold() in executors:
        problems.append(f"Griller task {target} is owned by {owner}, the same agent as the "
                        f"{executors[owner.strip().casefold()]} Executor; accepted means grilled by someone else")
    return problems


def griller_binding_errors(target, latest, evidence, ours):
    """The griller's latest return names the plan it grilled and the digest of that plan's design decisions."""
    digests = re.findall(r"(?mi)^Design digest:[ \t]*(.*?)[ \t]*$", latest)
    plans = re.findall(r"(?mi)^Plan path:[ \t]*(.*?)[ \t]*$", latest)
    problems = []
    if len(digests) != 1 or not re.fullmatch(r"sha256:[0-9a-f]{64}", digests[0], re.I):
        problems.append(f"Griller task {target} does not bind itself to the design decisions: its latest return needs "
                        "exactly one 'Design digest: sha256:<digest>' line (validate_contracts.py design-digest <plan> "
                        f"prints it), found {len(digests)}")
    elif ours and digests[0][len("sha256:"):].lower() != ours:
        problems.append(f"Griller task {target} recorded design digest {digests[0]}, but these design decisions hash to "
                        f"sha256:{ours}: the griller did not grill these design decisions; a design edit needs a new "
                        "griller return, a scope edit does not")
    if len(plans) != 1 or not workflow_value(plans[0]):
        problems.append(f"Griller task {target} does not name the plan it grilled: its latest return needs exactly one "
                        f"'Plan path: <plan>' line, found {len(plans)}" + (placeholder_note(plans[0]) if len(plans) == 1 else ""))
    else:
        named = workflow_path(plans[0], target)
        try:
            same = os.path.samefile(named, evidence)
        except OSError:
            same = False
        if not same:
            problems.append(f"Griller task {target} names plan {named}, not {evidence}: the griller did not grill this plan")
    return problems


def visible(text):
    """What a reader sees of a return: fenced examples and HTML comments (an unclosed one runs to the end) are dropped."""
    return "\n".join(row.shown for row in scan_markdown(text)[0] if not row.fenced)


def workflow_procedure_paths(text, record):
    """Resolved paths of the Procedure lines in the Workflow section ahead of any return."""
    found = set()
    for heading, block in sections(workflow_text(text).split("\n## Return", 1)[0], 2):
        if heading.lower() == "workflow":
            for key, value in re.findall(r"(?mi)^[ \t]*(?:- )?(procedures?|required skill paths):[ \t]*(.*)$", block):
                parts = [value] if key.lower() == "procedure" else value.split(",")
                found.update(workflow_path(part.strip(), record).resolve() for part in parts if part.strip())
    return found


def parent_executors(fields, record, read_text):
    """Whom a griller must differ from: this record's Executor and, for a worker brief, its parent State's."""
    names = {fields.get("executor", "").strip().casefold(): "record's"}
    problem = None
    if fields.get("state"):
        target = workflow_path(fields["state"].split("#", 1)[0], record)
        reason = "it has no 'Executor:' line in its '## Workflow' section"
        try:
            state = workflow_text(read_text(target))
        except (OSError, UnicodeError) as e:
            state, reason = "", f"it cannot be read ({e})"
        parents = set()
        for heading, block in sections(state, 2):
            if heading.lower() == "workflow":
                for name in re.findall(r"(?mi)^[ \t]*(?:- )?Executor:[ \t]*(\S.*)$", block):
                    parents.add(name.strip().casefold())
        for name in parents:
            names.setdefault(name, "parent's")
        if not parents:
            problem = f"cannot determine the parent's Executor from State {target}: {reason}, so no griller can be shown to differ from it"
    names.pop("", None)
    return names, problem


# ---------------------------------------------------------------- required steps, cuts and read order

STEP_ROUTES = ("research", "plan", "build", "debug", "review")
STEPS_SECTION = "Required steps"
READ_NOTES = []  # timing the record leaves unverified, printed after a pass; main() resets it per run
CUT_SOURCE_LIMIT = 2 * 1024 * 1024  # the per-file ceiling of the Herdr adapter's bounded reader, so both say the same
STAMP_RE = re.compile(r"(?i)(?<![\w-])at:\s*(\d\S*)")  # case and a space after the colon do not matter; "looked at: it" is prose


def step_key(text):
    """A checklist label or step name, compared as words: case, punctuation and a leading 'to' do not matter."""
    words = re.findall(r"[a-z0-9]+", text.split(":", 1)[0].casefold())
    return " ".join(words[1:] if words[:1] == ["to"] and len(words) > 1 else words)


def step_matches(step, label):
    """`label` is a step_key: only the words before the label's ':' (or the whole label) name the step, so
    'Grilling skipped' and 'Review later' are not the steps 'grilling' and 'review'."""
    return label == step


def workflow_map_steps(map_text):
    """The map's `## Required steps` section: ({(route, branch): [step, ...]}, errors). Each line is
    `- <route>[, multi-session yes|no]: <step>, <step>, ...`; build needs both branches, every other route none."""
    secs = [b for h, b in sections(map_text, 2) if h.casefold() == STEPS_SECTION.casefold()]
    if not secs:
        return {}, [f"needs the section '## {STEPS_SECTION}', which lists the steps each route and branch requires"]
    repeats = [t for t in map_headings(map_text) if t.casefold() == STEPS_SECTION.casefold()]
    if len(repeats) > 1:
        return {}, [f"has the section '## {STEPS_SECTION}' {len(repeats)} times; it needs exactly one"]
    found, errors = {}, []
    for line in secs[0].splitlines():
        if not line.startswith("- ") or THEMATIC_BREAK_RE.match(line):
            continue
        m = re.fullmatch(r"- (\w+)(?:, multi-session (yes|no))?:[ \t]*(.*?)[ \t]*", line)
        names = [n.strip() for n in m.group(3).split(",")] if m else []
        if not m or m.group(1) not in STEP_ROUTES or not names or any(
                not re.fullmatch(r"[a-z][a-z-]*", n) for n in names):
            errors.append(f"has a malformed line in its 'Required steps' section, '{line[:80]}'; use "
                          f"'- <route>[, multi-session yes|no]: <step>, <step>' with route one of "
                          f"{', '.join(STEP_ROUTES)} and lower-case step names")
            continue
        key = (m.group(1), m.group(2))
        if key in found:
            errors.append(f"lists '{m.group(1)}{', multi-session ' + m.group(2) if m.group(2) else ''}' twice in its 'Required steps' section")
        elif len({step_key(n) for n in names}) != len(names):
            errors.append(f"repeats a step in the 'Required steps' line of '{m.group(1)}'")
        else:
            found[key] = names
    for route in STEP_ROUTES:
        wanted = (("build", "yes"), ("build", "no")) if route == "build" else ((route, None),)
        for key in wanted:
            if key not in found:
                errors.append(f"has no 'Required steps' line for '{key[0]}{', multi-session ' + key[1] if key[1] else ''}'; "
                              "every route, and build under each branch, needs one")
    return found, errors


def read_stamp(text):
    """('none' | 'bad' | 'ok', datetime) for the `at:<UTC time>` token in `text`."""
    m = STAMP_RE.search(text)
    if not m:
        return "none", None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ"):
        try:
            return "ok", datetime.strptime(m.group(1), fmt)
        except ValueError:
            pass
    return "bad", None


def inherited_workflow_lines(fields, record, read_text, key):
    """Values of `key:` lines in the parent State's Workflow section (a worker inherits the parent's decisions)."""
    if not fields.get("state"):
        return []
    try:
        state = workflow_text(read_text(workflow_path(fields["state"].split("#", 1)[0], record)))
    except (OSError, UnicodeError):
        return []
    found = []
    for heading, block in sections(state, 2):
        if heading.lower() == "workflow":
            found += [v.strip() for v in re.findall(r"(?mi)^[ \t]*(?:- )?" + key + r":[ \t]*(\S.*)$", block)]
    return found


def record_steps(map_steps, route, decision):
    """Step keys the map requires for the route and, on build, the recorded branch (both branches while none is
    recorded). Every route's steps when the route is not one the map lists, so a bad Route is reported once."""
    branch = re.match(r"multi-session:[ \t]*(yes|no)\b", decision or "", re.I)
    branch = branch.group(1).lower() if branch else None
    keys = {step_key(n) for (r, b), names in map_steps.items() for n in names
            if r == route and (route != "build" or branch in (None, b))}
    return keys or {step_key(n) for names in map_steps.values() for n in names}


def cut_source_problem(quote, source, record, read_text):
    """Why a cut's source does not hold its quote: a path (with an optional #anchor) must exist and contain the
    quote. Any other pointer ("the user, in the chat of 2026-10-17") is the reviewer's to read."""
    ref = source.split("#", 1)[0].strip()
    if not re.fullmatch(r"\S+", ref) or not ("/" in ref or re.search(r"\.[A-Za-z0-9]{1,6}$", ref)):
        return None
    target = workflow_path(ref, record)
    too_big = (f"Cut source {ref} is larger than {CUT_SOURCE_LIMIT} bytes ({target}); "
               "cite the part the human wrote in a smaller file")
    try:
        if os.stat(target).st_size > CUT_SOURCE_LIMIT:  # before the read, so every reader gives this one answer
            return too_big
        text = read_text(target)
    except (OSError, UnicodeError) as e:
        return f"Cut source {ref} is unavailable at {target} ({e})"
    if len(text.encode("utf-8")) > CUT_SOURCE_LIMIT:  # grew between the stat and the read
        return too_big
    def words(s):
        return " ".join(s.casefold().split())
    if words(quote.strip(" \t\"'\u201c\u201d\u2018\u2019")) not in words(text):
        return f"Cut source {ref} does not contain the quote {quote.strip()[:60]!r} ({target})"
    return None


def cut_errors(values, known, read_text):
    """Parse `Cut: <steps> | <the human's quote> | <source pointer>` lines, each paired with the record that holds it:
    (set of cut step keys, errors). `known` is the step keys of the record's route and branch."""
    cut, errors = set(), []
    for value, record in values:
        steps, bar, rest = value.partition(" | ")
        names = [n.strip() for n in steps.split(",") if n.strip()]
        if not names or not bar or not workflow_value(steps) or not quote_has_source(rest):
            errors.append("Cut needs the human's quote and a source pointer, "
                          f"'Cut: <steps> | <the human's own words> | <where they said it>', found '{value[:80]}'; "
                          "only the human cuts a step, and the lead cannot cut one itself" + placeholder_note(value))
            continue
        quote, _, source = rest.strip().rpartition(" | ")
        problem = cut_source_problem(quote, source, record, read_text)
        if problem:
            errors.append(problem)
            continue
        for name in names:
            if step_key(name) not in known:
                errors.append(f"Cut names '{name}', which is not a step the workflow map requires for this record's "
                              "route and branch")
            else:
                cut.add(step_key(name))
    return cut, errors


def required_step_errors(map_steps, route, decision, phase, gate, checklist, cut, map_path):
    """Steps the workflow map requires for the route and the recorded branch, due when a later step is done,
    at the review gate (the steps before review), and at the accept gate or the report phase (all of them).
    A step still ahead of the record is pending, never a skip."""
    branch = re.match(r"multi-session:[ \t]*(yes|no)\b", decision or "", re.I)
    branch = branch.group(1).lower() if branch else None
    lists = {b: [step_key(n) for n in names] for (r, b), names in map_steps.items() if r == route}
    shown = {step_key(n): n for (r, _), names in map_steps.items() if r == route for n in names}
    if not lists:
        return []
    unknown = route == "build" and branch is None
    steps = lists["yes"] if unknown else lists[branch if route == "build" else None]
    label = f"{route}, multi-session: {branch}" if route == "build" and branch else route
    done = {i for i, step in enumerate(steps)
            for mark, text in checklist if mark != " " and step_matches(step, step_key(text))}
    listed = {i for i, step in enumerate(steps) for _, text in checklist if step_matches(step, step_key(text))}
    frontier = max(done, default=0)
    if gate == "review" and "review" in steps:
        frontier = max(frontier, steps.index("review"))
    if gate == "accept" or phase in ("report", "deliver"):
        frontier = len(steps)
    owed = [(i, step) for i, step in enumerate(steps[:frontier]) if i not in done and step not in cut]
    if unknown and any(step not in lists["no"] for _, step in owed):
        return ["Route decision is not recorded: the workflow map's required steps for build depend on Ask Matt's "
                "multi-session branch, and the record is already past the steps that differ. Record it "
                "('Route decision: multi-session: yes; spec: ...; tickets: ...' or 'multi-session: no; reason: ...') "
                "before the work that depends on it"]
    return [f"Phase checklist is missing the required step '{shown[step]}' for route {label}: the workflow map "
            f"requires it ({map_path.name}) and the record is past it"
            + ("; it is listed but not done" if i in listed else "")
            + f". Only the human can cut it: record 'Cut: {shown[step]} | <the human's own words> | <where they said it>'"
            for i, step in owed]


ROUTER_SKILLS = {"ask-matt", "engineering-workflow", "team-lead"}  # read at entry, whatever the phase
PHASE_WORDS = set().union(*ROUTE_PHASES.values())


def workflow_map_phases(map_text):
    """{skill: {phase, ...}}: the phase words each map row's 'Route and phase' cell names after a colon, before any
    parenthesis. A row that names none (all: any phase boundary) maps to an empty set."""
    found = {}
    for line in map_text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or map_separator(line) or len(cells) < 2:
            continue
        words = set()
        for segment in cells[1].split("(")[0].split(";"):
            _, colon, after = segment.partition(":")
            if colon:
                words |= set(re.findall(r"[a-z]+", after.casefold())) & PHASE_WORDS
        found.setdefault(cells[0], words)
    return found

# The step a body's map row governs when the row's own phase word is not it (correction 28.2): the grilling bodies
# govern grilling, the producers their own step, tdd implement, code-review review, writing-for-agents (loaded with
# retro) retro; ddd-scope and ddd-ground serve the research and plan phases, which have no start step and precede implement.
GOVERNED_STEP = {
    **dict.fromkeys(("grilling", "grill-with-docs", "domain-modeling"), {"grilling"}),
    "to-spec": {"to-spec"}, "to-tickets": {"to-tickets"}, "implement": {"implement"}, "tdd": {"implement"},
    "code-review": {"review"}, "retro": {"retro"}, "writing-for-agents": {"retro"},
    "ddd-scope": {"implement"}, "ddd-ground": {"implement"},
}


def valid_start_steps(map_steps):
    """The names `Check: start <step>` may carry: the map's Required steps and the routes' phase words."""
    return {name for names in map_steps.values() for name in names} | PHASE_WORDS


def start_times(checks, valid=None):
    """({step: [time, ...]}, errors) from the passed `Check: start <step> | passed | ... at:<UTC time>` lines. With
    `valid`, a start Check naming anything else is an error: an unknown name would leave every read unheld."""
    starts, errors = {}, []
    for value in checks:
        parts = [p.strip() for p in value.split("|", 2)]
        named = re.fullmatch(r"start[ \t]+(.+)", " ".join(parts[0].casefold().split()))
        if named and valid is not None and named.group(1) not in valid:
            errors.append(f"Check '{parts[0]}' names an unknown step '{named.group(1)}': a start Check names a step of "
                          "the workflow map's Required steps (scope, grilling, to-spec, to-tickets, implement, review, "
                          "retro, ...) or the route's phase word")
        elif named and len(parts) == 3 and parts[1] == "passed":
            state, when = read_stamp(parts[2])
            if state == "ok":
                starts.setdefault(named.group(1), []).append(when)
            elif state == "bad":
                errors.append(f"Check '{parts[0]}' has an at: stamp that is not an ISO-8601 UTC time "
                              "(2026-10-17T10:00:00Z)")
    return starts, errors


def strip_stamp(value):
    """`value` without its `at:<UTC time>` token."""
    m = STAMP_RE.search(value)
    return (value[:m.start()].rstrip() + value[m.end():]) if m else value


def route_decision_order_errors(value, inherited, checks):
    """A worker's Route decision is the parent State's. With stamped start Checks in the record, the decision carries
    an `at:` time no later than the earliest start Check of implement: the branch is recorded before execution."""
    def plain(text):
        return " ".join(strip_stamp(text).casefold().split())
    errors = []
    if inherited and plain(value) != plain(inherited[0]):
        errors.append(f"Route decision '{strip_stamp(value)[:60]}' differs from the parent State's "
                      f"'{strip_stamp(inherited[0])[:60]}': the branch is the parent's to record, not the worker's")
    starts, _ = start_times(checks)
    if starts:
        state, when = read_stamp(value)
        implement = min(starts.get("implement", []), default=None)
        if state == "none":
            errors.append("Route decision needs an at:<UTC time> (at:2026-10-17T10:00:00Z) because the record has "
                          "stamped start Checks: the branch must be recorded before execution, and an unstamped "
                          "branch cannot show that")
        elif state == "bad":
            errors.append("Route decision has an at: stamp that is not an ISO-8601 UTC time (2026-10-17T10:00:00Z)")
        elif implement and when > implement:
            errors.append(f"Route decision is stamped {when:%Y-%m-%dT%H:%M:%SZ}, after the "
                          f"{implement:%Y-%m-%dT%H:%M:%SZ} start Check of phase 'implement': the branch was recorded "
                          "after execution began")
    return errors


def read_identity(target, record):
    """The body a `Loaded:` path names: the path resolved from the record's folder, as the load check resolves it."""
    path = workflow_path(target, record)
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return path


def pool_roles(pool):
    """{resolved SKILL.md: [pool entry names, sorted]} for the canonical pool, built once per check. An entry whose
    SKILL.md does not exist or does not resolve (dangling, cyclic) cannot be any read's body, so it is skipped. A pool
    that does not exist has no roles; a pool or entry that exists but cannot be read raises PermissionError or OSError,
    since no role can then be told from an unregistered one."""
    roles = {}
    try:
        entries = sorted(pool.iterdir())
    except FileNotFoundError:
        return roles
    for entry in entries:
        try:
            body = (entry / "SKILL.md").resolve()
            body.stat()  # is_file() reports an unreadable body as absent (3.14); stat() raises PermissionError
            if body.is_file():
                roles.setdefault(body, []).append(entry.name)
        except PermissionError:
            raise
        except (OSError, RuntimeError):
            continue
    return roles


def read_skill_names(body, roles):
    """The skills a resolved body stands for: its canonical pool names, else (an unregistered or custom reference)
    the name of the folder it sits in."""
    return roles.get(body) or ([body.parent.name] if body.name == "SKILL.md" else [""])


def late_read_errors(load_values, checks, phase, map_phases, valid=None, *, record, pool=None):
    """A body is on time when at least one `Loaded:` read of it is stamped no later than the earliest passed start
    Check (`Check: start <step> | passed | ... at:<UTC time>`) of the step its map row governs: any step for the
    router and entry bodies, the row's own step otherwise, and the record's `Phase` for a body whose row names none.
    A later reload never makes an earlier on-time read late; a body with no on-time read is refused. Order evidence
    the record writes about itself; an unstamped line stays unverified. The body a path resolves to (from the
    record's folder) is its identity: it groups the reads, whatever the path is called. The skill comes from the
    canonical pool entries that resolve to that body (`pool`, default ~/.agents/skills), not from its folder's
    incidental name; pool names sharing one body hold the read to the earliest of their governed steps."""
    starts, errors = start_times(checks, valid)
    pool = pool or Path.home() / ".agents" / "skills"
    try:
        roles = pool_roles(pool)
    except OSError as e:
        return errors + [f"the skill pool {pool} cannot be read ({e}): a read's skill comes from the pool entry "
                         "that resolves to its body, so no Loaded read can be timed until every pool entry can be read"]
    bodies, unstamped = {}, 0
    for value in load_values:
        target = value.partition("|")[0].strip()
        state, when = read_stamp(value.partition("|")[2])
        bodies.setdefault(read_identity(target, record), []).append((target, state, when))
    for body, reads in bodies.items():
        target = reads[0][0]
        names = read_skill_names(body, roles)
        if ROUTER_SKILLS.intersection(names):
            wanted = set(starts)
        else:
            wanted = set().union(*(GOVERNED_STEP.get(n) or map_phases.get(n) or set() for n in names)) or {phase}
        held = {step: min(times) for step, times in starts.items() if step in wanted}
        for _, state, _ in reads:
            if state == "bad":
                errors.append(f"Loaded {target} has an at: stamp that is not an ISO-8601 UTC time (2026-10-17T10:00:00Z)")
        if any(state == "bad" for _, state, _ in reads):
            continue
        stamped = [when for _, state, when in reads if state == "ok"]
        if not held or not stamped:
            unstamped += len(reads)
            continue
        step, start = min(held.items(), key=lambda item: item[1])
        if min(stamped) > start:
            errors.append(f"Loaded {target} is stamped {min(stamped):%Y-%m-%dT%H:%M:%SZ}, after the "
                          f"{start:%Y-%m-%dT%H:%M:%SZ} start Check of step '{step}', and no earlier read of this body is "
                          "recorded: a read must come before the work, and a late read cannot establish earlier "
                          "compliance")
        elif len(stamped) < len(reads):
            unstamped += len(reads) - len(stamped)
    if unstamped:
        READ_NOTES.append(f"{unstamped} Loaded line(s) have no at: time, or no stamped 'Check: start <step>' for "
                          "the step that needs their body, so their order against the work is unverified")
    return errors


WORKFLOW_MAP = ("engineering-workflow", "references", "workflow-map.md")
WORKFLOW_MAP_COLUMNS = ("Route and phase", "Invoker", "Invocation path", "Dependencies", "Evidence", "Anchor")
WORKFLOW_MAP_ROUTES = r"\b(?:research|plan|build|debug|review|all|standalone)\b"
# The shipped set (Mifal's plan D9), by map table.
WORKFLOW_MAP_TABLES = (
    ("Ask Matt rows", None, "Skill", "ask-matt", (
        "ask-matt", "grill-with-docs", "grill-me", "grilling", "domain-modeling", "prototype", "handoff",
        "to-spec", "to-tickets", "implement", "implement-spec", "tdd", "code-review", "pr", "retro", "triage",
        "diagnosing-bugs", "wayfinder", "improve-codebase-architecture", "codebase-design", "research",
        "to-questionnaire", "wizard", "wait-what", "teach", "writing-for-agents", "setup-matt-pocock-skills")),
    ("Local attachments", None, "Skill", "attaches", (
        "receiving-code-review", "ddd", "ddd-scope", "ddd-ground", "ddd-verify",
        "frontend-design", "agent-browser")),
    ("Factory section", "Factory core", "Skill", "factory", (
        "engineering-workflow", "team-lead", "herdr-adapter", "validate-contracts", "setup-pre-commit")),
    ("Factory section", "Starts Ask Matt does not cover", "Start", "factory", (
        "operational or one-off task", "team coordination")),
)


def workflow_map_errors(pool, read_text):
    """Hold a Matt gate until the workflow map was reviewed against the installed Ask Matt body."""
    map_path = pool.joinpath(*WORKFLOW_MAP)
    try:
        map_text = workflow_text(read_text(map_path))
    except (OSError, UnicodeError) as e:
        return [f"workflow map unavailable: {map_path} ({e}); the gates read it, so a Matt gate cannot pass without it"]
    try:
        ask_matt = read_text(pool / "ask-matt" / "SKILL.md")
    except (OSError, UnicodeError) as e:
        return [f"Ask Matt body unavailable, so workflow map {map_path} cannot be held to it ({e})"]
    installed = hashlib.sha256(ask_matt.encode("utf-8")).hexdigest()
    lines = re.findall(r"(?m)^Ask Matt body:.*$", map_text)
    pins = [m.group(1) for m in (re.fullmatch(r"Ask Matt body: sha256:([0-9a-f]{64})\s*", line) for line in lines) if m]
    if len(lines) != 1 or len(pins) != 1:
        return [f"workflow map {map_path} must record exactly one 'Ask Matt body: sha256:<64 hex digits>' line"]
    if pins[0] != installed:
        return [f"Ask Matt changed since the workflow map {map_path} was reviewed: the map records Ask Matt body "
                f"sha256:{pins[0]}, the installed body is sha256:{installed}. Review the map against the new body, "
                "then update its 'Ask Matt body:' line"]
    # A repeated section or a table outside the four would read as authoritative to a human but never to the gate.
    errors = []
    titles = [title.casefold() for title in map_headings(map_text)]
    for level, name in ([(2, h) for h in dict.fromkeys(t[0] for t in WORKFLOW_MAP_TABLES)]
                        + [(3, t[1]) for t in WORKFLOW_MAP_TABLES if t[1]]):
        count = titles.count(name.casefold())
        if count > 1:
            errors.append(f"workflow map {map_path} has the section '{'#' * level} {name}' {count} times; "
                          "it needs exactly one")
    tables = sum(1 for line in map_text.splitlines() if map_separator(line))
    if tables != len(WORKFLOW_MAP_TABLES):
        errors.append(f"workflow map {map_path} has {tables} tables; it needs {len(WORKFLOW_MAP_TABLES)}, "
                      "one under each of its table sections")
    if errors:
        return errors
    ask_matt_rows = []
    for heading, subheading, column, kind, shipped in WORKFLOW_MAP_TABLES:
        block = next((b for h, b in sections(map_text, 2) if h == heading), None)
        if block is not None and subheading:
            block = next((b for h, b in sections(block, 3) if h == subheading), None)
        if block is None:
            errors.append(f"workflow map {map_path} needs the section '{'### ' + subheading if subheading else '## ' + heading}'")
            continue
        header, rows = workflow_map_rows(block)
        expected = (column,) + WORKFLOW_MAP_COLUMNS
        if tuple(header) != expected:
            errors.append(f"workflow map {map_path} table under '{subheading or heading}' needs the columns "
                          + " | ".join(expected))
            continue
        names = [cells[0].strip("`") for cells in rows]
        if kind == "ask-matt":
            ask_matt_rows = names
        for name in shipped:
            if name not in names:
                errors.append(f"workflow map {map_path} has no row for shipped skill '{name}' under '{subheading or heading}'")
        for name in sorted(set(names) - set(shipped)):
            errors.append(f"workflow map {map_path} lists '{name}', which is not in the shipped set")
        for name in sorted({n for n in names if names.count(n) > 1}):
            errors.append(f"workflow map {map_path} lists '{name}' more than once")
        for cells in rows:
            name, anchor = cells[0].strip("`"), cells[-1]
            if len(cells) != len(expected):
                errors.append(f"workflow map {map_path} row '{name}' needs {len(expected)} cells, found {len(cells)}")
                continue
            for cell_column, cell in zip(expected, cells):
                if not workflow_value(cell):
                    errors.append(f"workflow map {map_path} row '{name}' has an empty or placeholder '{cell_column}' cell")
            if not re.search(WORKFLOW_MAP_ROUTES, cells[1].lower()):
                errors.append(f"workflow map {map_path} row '{name}' Route and phase names no route "
                              "(research, plan, build, debug, review, all or standalone)")
            if not re.search(r"\b(?:lead|worker)\b", cells[2].lower()):
                errors.append(f"workflow map {map_path} row '{name}' Invoker names neither the lead nor a worker")
            if not re.match(kind + r":\s*\S", anchor):
                errors.append(f"workflow map {map_path} row '{name}' has Anchor '{anchor}', but rows under "
                              f"'{heading}' need an Anchor that starts '{kind}:'; a row restates Ask Matt, attaches to "
                              "an Ask Matt row or sits in the factory section, and never infers a branch")
            elif kind == "ask-matt" and name != "ask-matt" and not map_names(name, ask_matt):
                errors.append(f"workflow map {map_path} row '{name}' sits under 'Ask Matt rows', but the installed "
                              f"Ask Matt body does not name /{name}; a row cannot place a skill Ask Matt does not place")
            elif kind == "factory" and column == "Skill" and map_names(name, ask_matt):
                errors.append(f"workflow map {map_path} row '{name}' sits in the factory section, but the installed "
                              f"Ask Matt body names /{name}; it belongs under 'Ask Matt rows'")
            elif kind == "attaches":
                for target in re.split(r"\s*,\s*", anchor.partition(":")[2].strip()):
                    if target not in ask_matt_rows:
                        errors.append(f"workflow map {map_path} row '{name}' attaches to '{target}', which is not an Ask Matt row")
    errors.extend(f"workflow map {map_path} {e}" for e in workflow_map_steps(map_text)[1])
    return errors


def map_names(name, ask_matt):
    """True when the Ask Matt body names the skill as /skill."""
    return re.search(r"(?<![\w/.-])/" + re.escape(name) + r"(?![\w-])", ask_matt) is not None


def map_separator(line):
    """True for a GFM table's delimiter row: up to 3 spaces of indent, outer pipes optional, cells of hyphens
    with optional colons. A pipe is required, so a bare `---` stays a thematic break or a setext underline."""
    return "|" in line and re.fullmatch(r" {0,3}(?![ \t])\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*", line) is not None


def map_headings(text):
    """Heading titles as a GFM reader sees them: ATX headings (up to 3 spaces of indent, optional closing `#` run)
    and setext headings (a paragraph line over `===` or `---`), at any level."""
    titles, paragraph = [], ""
    for line in text.splitlines():
        atx = re.fullmatch(r" {0,3}#{1,6}(?:[ \t]+(.*))?", line)
        underline = re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", line)
        if atx:
            titles.append(re.sub(r"(?:^|[ \t]+)#+$", "", (atx.group(1) or "").strip()).strip())
        elif underline and paragraph:
            titles.append(paragraph)
        # A line is a paragraph's text unless it is blank, indented as code, a table row or an underline.
        paragraph = "" if atx or underline or re.match(r"\s*$|    |\t|\|", line) else line.strip()
    return titles


def workflow_map_rows(block):
    """Header and data rows of the pipe table in `block`; the dashed row is skipped."""
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in block.splitlines() if line.startswith("|") and not map_separator(line)]
    return (rows[0], rows[1:]) if rows else ([], [])


def workflow_claims(body):
    """One parsing rule for the opt-in brief and acceptance claim surface."""
    done = find_section(sections(body, 2), "Done means") or ""
    return [tuple(part.strip() for part in line.strip()[2:].partition(":"))
            for line in done.splitlines() if line.strip().startswith("- ")]


CHECKBOX_RE = re.compile(r"^\s*- \[[ xX]\]\s+\S")
THEMATIC_BREAK_RE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
LIST_MARKER_RE = re.compile(r"^\s*(?:(?:[-*+]|\d+[.)])(?=[\s\[]|$)|-(?=[^\s-]))")


def marker_line(line):
    """A line that looks like a list item: list marker, numbered item or a dash glued to its text."""
    return bool(LIST_MARKER_RE.match(line)) and not THEMATIC_BREAK_RE.match(line)


def workflow_value(value):
    return bool(value.strip()) and value.lower() not in {
        "tbd", "todo", "pending", "unresolved", "unknown", "n/a", "none", "...",
    } and not re.search(r"<[^>]+>", value)


def placeholder_note(*values):
    """Why `workflow_value` refused text that only looks unfilled: names the first line holding angle-bracketed text.

    Empty when no value holds any, so a refusal for another reason stays unadorned. It never decides a verdict."""
    for value in values:
        found = re.search(r"<[^>]+>", value)
        if found:
            start = value.rfind("\n", 0, found.start()) + 1
            end = value.find("\n", found.start())
            line = value[start:end if end >= 0 else len(value)].strip()
            return (f" ('{line[:80]}' looks like a placeholder: text in angle brackets is read as unfilled; "
                    "write formats without angle brackets)")
    return ""


def workflow_path(value, record):
    target = Path(value).expanduser()
    return target if target.is_absolute() else record.parent / target


def workflow_evidence(value, record, read_text, label, headings):
    pin = re.fullmatch(r"sha256:([0-9a-f]{64})\s*\|\s*(.+)", value, re.I)
    if not pin:
        return "", [f"{label} needs 'sha256:<digest> | <existing evidence artifact>'"], ""
    target = workflow_path(pin.group(2).strip(), record)
    try:
        text = read_text(target)
    except (OSError, UnicodeError) as e:
        return "", [f"{label} evidence unavailable: {e}"], ""
    errors = []
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != pin.group(1).lower():
        errors.append(f"{label} evidence changed; reconcile it before proceeding")
    body = visible(text)
    for name in headings:
        blocks = [b for h, b in sections(body, 2) if h.lower() == name.lower()]
        if len(blocks) != 1 or not workflow_value(blocks[0].strip()):
            errors.append(f"{label} evidence needs one nonempty '## {name}' section"
                          + (placeholder_note(blocks[0].strip()) if len(blocks) == 1 else ""))
    return body, errors, text


FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
CODE_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
UNCLOSED_MESSAGE = "unclosed comment or fence in {}; the gate cannot tell what is visible"


class Scanned:
    """One physical line as a CommonMark reader sees it: `fenced` for a fence delimiter or its content, `shown` for the
    line with HTML comment spans removed, `in_comment` when the line starts inside a comment."""
    __slots__ = ("line", "fenced", "shown", "in_comment")

    def __init__(self, line, fenced, shown, in_comment):
        self.line, self.fenced, self.shown, self.in_comment = line, fenced, shown, in_comment


def scan_markdown(text):
    """The one line scanner behind every fence and comment decision. Comment and fence state exclude each other and
    are read in order: inside a comment only `-->` is looked for, inside a fence only its closing fence, otherwise
    openings are detected. A backtick fence whose info string holds a backtick is a code span, and a `<!--` inside a
    code span opens nothing. Returns ([Scanned], unclosed, opened): `unclosed` is 'comment', 'fence' or None, and
    `opened` the index of the line that began it."""
    rows, fence, comment, opened = [], None, False, None
    for number, line in enumerate(text.splitlines()):
        fenced, started_in_comment = False, comment
        if fence:
            fenced = True
            if re.fullmatch(" {0,3}" + re.escape(fence[0]) + "{" + str(fence[1]) + r",}[ \t]*", line):
                fence, opened = None, None
        elif not comment:
            opening = FENCE_OPEN_RE.match(line)
            if opening and not (opening.group(1)[0] == "`" and "`" in opening.group(2)):
                fence, fenced, opened = (opening.group(1)[0], len(opening.group(1))), True, number
        shown = ""
        if not fenced:
            masked = CODE_SPAN_RE.sub(lambda m: " " * len(m.group(0)), line)
            pos, search, parts = 0, 0, []
            while True:
                if comment:
                    end = line.find("-->", search)
                    if end < 0:
                        break
                    comment, opened, pos = False, None, end + 3
                else:
                    start = masked.find("<!--", pos)
                    if start < 0:
                        parts.append(line[pos:])
                        break
                    parts.append(line[pos:start])
                    comment, opened, search = True, number, start + 2
            shown = "".join(parts)
        rows.append(Scanned(line, fenced, shown, started_in_comment))
    return rows, ("fence" if fence else "comment" if comment else None), opened


def workflow_text(text):
    """Examples in fences cannot satisfy the opt-in contract. Comments stay: a fence marker inside one is not a fence."""
    return "\n".join(row.line for row in scan_markdown(text)[0] if not row.fenced)


def workflow_snapshot(value, record, body_digest=None, read_text=None, guard=False):
    """Check a pinned review identity. `guard` (build/debug) adds two refusals that read nothing
    beyond the caller's own callbacks: a .diff/.patch artifact name, and a JSON snapshot whose scope is empty."""
    artifact = re.fullmatch(r"sha256:([0-9a-f]{64})\s*\|\s*(.+)", value, re.I)
    if artifact:
        target = workflow_path(artifact.group(2).strip(), record)
        if guard and target.suffix.lower() in (".diff", ".patch"):
            return [f"Snapshot artifact {target.name} is a .diff/.patch file; a frozen diff does not identify live "
                    "code on build/debug work. Pin the changed live file or a review-snapshot JSON. "
                    "This is a filename heuristic, not proof of review scope"]
        if not target.is_file():
            return [f"Snapshot artifact unavailable: {target}"]
        try:
            digest = (body_digest or workflow_digest)(target)
        except OSError as e:
            return [f"Snapshot cannot be checked: {e}"]
        return [] if digest == artifact.group(1).lower() else ["Snapshot artifact changed; review the affected work again"]
    snapshot = workflow_path(value, record)
    if guard and read_text:
        try:
            saved = json.loads(read_text(snapshot))
        except (OSError, UnicodeError) as e:
            return [f"Snapshot cannot be read: {e}"]
        except ValueError:
            saved = None
        if isinstance(saved, dict) and saved.get("reviewable") is False:
            return ["Snapshot JSON has reviewable: false (its --path scope holds no changed file); "
                    "take a snapshot whose scope covers the changed files"]
    tool = Path.home() / ".agents" / "mifal" / "tools" / "review-snapshot.py"
    try:
        result = subprocess.run([sys.executable, "-B", str(tool), "--check", str(snapshot)],
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [f"Snapshot check unavailable: {e}"]
    return [] if result.returncode == 0 else ["Snapshot not current: " + result.stderr.strip()]


def regular_stream(path):
    """Open `path` for binary reading, refusing anything but a regular file.

    O_NONBLOCK keeps open(2) from waiting for a FIFO writer; the kind is read from the opened
    descriptor, not a separate stat, so the object checked is the object read. The stream owns the
    descriptor from the moment it exists, so a refusal closes it. No size cap and no sandbox claim."""
    source = open(path, "rb", opener=lambda name, flags: os.open(name, flags | os.O_NONBLOCK))
    try:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise OSError(f"not a regular file: {path}")
    except BaseException:
        source.close()
        raise
    return source


def regular_text(path):
    with regular_stream(path) as source:
        return source.read().decode("utf-8")


def workflow_digest(path):
    digest = hashlib.sha256()
    with regular_stream(path) as source:
        for chunk in iter(lambda: source.read(262144), b""):
            digest.update(chunk)
    return digest.hexdigest()

def validate_brief(text: str, name: str):
    errors = []
    fields, body, fm_errors = parse_frontmatter(text)
    if fm_errors:
        return [f"{name}: {e}" for e in fm_errors]
    hints = {
        "task": "add 'task: <n>' — the stable task id from the team record",
        "owner": "add 'owner: <member>' — who holds this task",
        "latitude": "add 'latitude: look|propose|do-tell|own'",
        "return": "add 'return: <path>' — the file the member writes and the "
                  "doorbell names",
    }
    for field in REQUIRED_BRIEF_FIELDS:
        if not fields.get(field):
            errors.append(f"missing frontmatter '{field}'; {hints[field]}")
    task = fields.get("task", "")
    if task and not re.match(r"^[0-9]+$", task):
        errors.append(f"bad task id '{task}'; use a plain number like '7'")
    attempt = fields.get("attempt", "")
    if attempt:
        m = re.match(r"^([0-9]+)\.([0-9]+)$", attempt)
        if not m:
            errors.append(
                f"bad attempt id '{attempt}'; use '<task>.<n>', e.g. "
                f"'{task or '7'}.2'"
            )
        elif task and m.group(1) != task:
            errors.append(
                f"attempt id '{attempt}' must extend the task id; expected "
                f"'{task}.<n>', e.g. '{task}.2'"
            )
    latitude = fields.get("latitude", "")
    if latitude and latitude.strip().lower() not in LATITUDES:
        errors.append(
            f"unknown latitude '{latitude}'; expected one of "
            f"look, propose, do-tell, own"
        )
    ret = fields.get("return", "")
    if ret and len(ret.split()) != 1:
        errors.append(
            f"return path '{ret}' must be a single path token (no spaces)"
        )

    secs = sections(body, 2)
    # The brief ends where a return (receipt) begins, if one is present.
    brief_secs = []
    for heading, text_ in secs:
        if heading.lower().startswith("return"):
            break
        brief_secs.append((heading, text_))
    for name_ in REQUIRED_BRIEF_SECTIONS:
        if find_section(brief_secs, name_) is None:
            errors.append(
                f"missing section '## {name_}'; the brief contract requires: "
                f"{', '.join(REQUIRED_BRIEF_SECTIONS)}"
            )
    done_means = find_section(brief_secs, "Done means")
    if (
        done_means is not None
        and done_means.strip()
        and not any(
            line.lstrip().startswith("- ") for line in done_means.splitlines()
        )
    ):
        # An empty 'Done means' is an unfilled skeleton (the contract's own
        # template ships that way); prose without claim lines is the error.
        errors.append(
            "section 'Done means' names no claims; add one "
            "'- <claim>: <check>' line per thing done means"
        )
    return [f"{name}: {e}" for e in errors]


# ---------------------------------------------------------------- receipt

CLAIM_RE = re.compile(r"^-\s*(?P<claim>[^:]+?):\s*(?P<status>passed|failed|untested)\b")

LEVEL2_HEADING_RE = re.compile(r"^##\s+[^\n]*$", re.M)
RETURN_LABEL_RE = re.compile(r"^##\s+Return\b")
ATTEMPT_IN_LABEL_RE = re.compile(r"\battempt\s+([0-9]+\.[0-9]+)\b", re.I)
CLOSES_LINE_RE = re.compile(r"^Closes:\s*(\S+)\s*$", re.M)


def split_returns(text: str):
    """Split a task file into its returns: one (label, portion) per
    '## Return' heading that starts a receipt.

    A heading starts a receipt when it names an attempt ('## Return —
    attempt 7.2') or its body carries a 'Closes:' line — this keeps the
    brief's own '## Return' section (return path + doorbell line, per the
    brief template) from being mistaken for a receipt. Each portion ends at
    the next level-2 heading, so corrections that append returns (the
    designed norm) validate independently. Falls back to the whole text
    when no receipt heading is found.
    """
    headings = list(LEVEL2_HEADING_RE.finditer(text))
    returns = []
    for i, h in enumerate(headings):
        if not RETURN_LABEL_RE.match(h.group(0)):
            continue
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        portion = text[h.end():end]
        label = h.group(0)[2:].strip()
        if ATTEMPT_IN_LABEL_RE.search(label) or CLOSES_LINE_RE.search(portion):
            returns.append((label, portion))
    if not returns:
        return [("", text)]
    return returns


def validate_receipt(text: str, name: str):
    errors = []
    returns = split_returns(text)
    multi = len(returns) > 1

    # Cross-check 'Closes:' ids against the file's own frontmatter, when
    # the file has one (a standalone return file has none).
    fields, _, fm_errors = parse_frontmatter(text)
    fm_task = None
    present_attempts = set()
    if not fm_errors and fields:
        fm_task = fields.get("task") or None
        if fields.get("attempt"):
            present_attempts.add(fields["attempt"])
    for label, _ in returns:
        m = ATTEMPT_IN_LABEL_RE.search(label)
        if m:
            present_attempts.add(m.group(1))

    for label, portion in returns:
        prefix = f"{name}: {label}: " if multi else f"{name}: "

        closes = CLOSES_LINE_RE.findall(portion)
        if not closes:
            errors.append(
                prefix +
                "missing 'Closes: <id>'; close the task id explicitly, e.g. "
                "'Closes: 7' — delivery is proven by receipts, never by "
                "transport return codes"
            )
        for cid in closes:
            if not TASK_ID_RE.match(cid):
                errors.append(
                    prefix +
                    f"bad Closes id '{cid}'; use a task id ('7') or an "
                    f"attempt id ('7.2')"
                )
            elif fm_task and not closes_task(cid, fm_task, present_attempts):
                known = ", ".join(sorted(present_attempts)) or "none yet"
                errors.append(
                    prefix +
                    f"Closes id '{cid}' does not match this file's "
                    f"task '{fm_task}'; close '{fm_task}' or an attempt "
                    f"present in this file ({known})"
                )

        secs = sections(portion, 3)
        for name_ in REQUIRED_RECEIPT_SECTIONS:
            if find_section(secs, name_) is None:
                errors.append(
                    prefix +
                    f"missing section '### {name_}'; the receipt contract "
                    f"requires: {', '.join(REQUIRED_RECEIPT_SECTIONS)}"
                )

        claims = find_section(secs, "Claims")
        if claims is not None:
            items = [
                line.strip()
                for line in claims.splitlines()
                if line.strip().startswith("- ")
            ]
            if not items:
                errors.append(
                    prefix +
                    "section 'Claims' has no claims; list each done-means "
                    "claim as '- <claim>: passed|failed|untested' with the "
                    "revision checked"
                )
            for item in items:
                if not CLAIM_RE.match(item):
                    errors.append(
                        prefix +
                        f"claim line '{item}' has no status; end it with "
                        f"': passed|failed|untested' plus the revision "
                        f"checked, e.g. '- suite-green: passed (rev c3d4e5f)'"
                    )

        sidecars = find_section(secs, "Sidecars")
        if sidecars is not None:
            for line in sidecars.splitlines():
                item = line.strip()
                if item.startswith("- ") and len(item[2:].split()) != 1:
                    errors.append(
                        prefix +
                        f"sidecar '{item[2:]}' must be a single artifact "
                        f"path (no spaces)"
                    )
    return errors


def closes_task(cid: str, task: str, present_attempts) -> bool:
    """A Closes id must be the task itself or an attempt of it that is
    actually present in the file (a return heading or the brief's
    frontmatter 'attempt')."""
    if cid == task:
        return True
    base, dot, _ = cid.partition(".")
    return bool(dot) and base == task and cid in present_attempts


# ---------------------------------------------------------------- selfcheck

def check_one(kind: str, path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return [
            f"{path.name}: not valid UTF-8 (byte offset {e.start}); save "
            f"the file as UTF-8"
        ]
    if kind == "doorbell":
        _, errors = parse_doorbell(text)
    elif kind == "brief":
        errors = validate_brief(text, path.name)
    else:
        errors = validate_receipt(text, path.name)
    return errors


def selfcheck(fixtures: Path) -> int:
    total = 0
    failures = []
    for kind, pattern in (("doorbell", "*.txt"), ("brief", "*.md"),
                          ("receipt", "*.md")):
        for expect_valid, sub in ((True, "good"), (False, "bad")):
            folder = fixtures / kind / sub
            if not folder.is_dir():
                failures.append(f"missing fixture folder {folder}")
                continue
            for f in sorted(folder.glob(pattern)):
                total += 1
                errors = check_one(kind, f)
                ok = not errors
                label = f"{kind}/{sub}/{f.name}"
                if ok == expect_valid:
                    verdict = "accepted" if ok else "rejected"
                    print(f"pass  {label} ({verdict}, as expected)")
                    if not ok:
                        print(f"      first error: {errors[0]}")
                else:
                    failures.append(label)
                    if ok:
                        print(f"FAIL  {label} (accepted, expected rejection)")
                    else:
                        print(f"FAIL  {label} (rejected, expected acceptance)")
                        for e in errors:
                            print(f"      {e}")

    demo_path = fixtures / "doorbell" / "good" / "done-basic.txt"
    if demo_path.is_file():
        record, _ = parse_doorbell(demo_path.read_text(encoding="utf-8"))
        print()
        print("doorbell demo — pane-visible text:")
        print(f"  {demo_path.read_text(encoding='utf-8').strip()}")
        print("doorbell demo — parsed record any agent can read:")
        print("  " + json.dumps(record))

    print()
    print(f"{total} fixture checks, {len(failures)} unexpected outcomes")
    return 1 if failures else 0


# ---------------------------------------------------------------- cli

def main(argv) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_door = sub.add_parser("doorbell", help="validate one doorbell line")
    p_door.add_argument("line")
    p_door.add_argument(
        "--parse", action="store_true",
        help="print the parsed record as JSON on success",
    )

    p_brief = sub.add_parser("brief", help="validate a brief file")
    p_brief.add_argument("path", type=Path)
    p_brief.add_argument("--matt", action="store_true", help="also check Matt preparation and selected paths")

    p_receipt = sub.add_parser(
        "receipt", help="validate a receipt (the return in a task file)"
    )
    p_receipt.add_argument("path", type=Path)
    p_receipt.add_argument("--matt", action="store_true", help="also check Matt preparation and the executor's current return reads")

    p_work = sub.add_parser("workflow", help="check recorded Matt gate evidence in existing state")
    p_work.add_argument("path", type=Path)
    p_work.add_argument("--gate", choices=("entry", "review", "accept"), required=True)

    p_read = sub.add_parser("read", help="print one complete UTF-8 body with its exact-buffer hash and size")
    p_read.add_argument("path", type=Path)

    p_digest = sub.add_parser("design-digest", help="print the digest of a plan's design decisions, minus its Griller: lines")
    p_digest.add_argument("path", type=Path)

    sub.add_parser("selfcheck", help="run the validator against its fixtures")

    args = parser.parse_args(argv)

    if args.cmd == "design-digest":
        try:
            digest, ambiguous = design_parts(regular_text(args.path.expanduser()))
        except (OSError, UnicodeError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if ambiguous:
            print("error: " + UNCLOSED_MESSAGE.format(args.path), file=sys.stderr)
            return 1
        if digest is None:
            print(f"error: {args.path}: no '## Design decisions' section", file=sys.stderr)
            return 1
        print(f"sha256:{digest}")
        return 0

    if args.cmd == "read":
        target = args.path.expanduser().resolve()
        try:
            data = target.read_bytes()
            data.decode("utf-8")
        except (OSError, UnicodeError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        footer = f"\n-- end of body {target} | sha256:{hashlib.sha256(data).hexdigest()} bytes:{len(data)} --\n"
        sys.stdout.buffer.write(data + footer.encode("utf-8"))
        return 0

    if args.cmd == "doorbell":
        record, errors = parse_doorbell(args.line)
        if errors:
            for e in errors:
                print(f"error: {e}", file=sys.stderr)
            return 1
        print("ok: doorbell")
        if args.parse:
            print(json.dumps(record, indent=2))
        return 0

    if args.cmd in ("brief", "receipt", "workflow"):
        path: Path = args.path
        if not path.is_file():
            print(f"error: no such file: {path}", file=sys.stderr)
            return 2
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            print(
                f"error: {path}: not valid UTF-8 (byte offset {e.start}); "
                f"save the file as UTF-8",
                file=sys.stderr,
            )
            return 1
        if args.cmd == "brief":
            errors = validate_brief(text, str(path))
        elif args.cmd == "receipt":
            errors = validate_receipt(text, str(path))
            if args.matt:
                errors += validate_brief(text, str(path))
        else:
            errors = []
        READ_NOTES.clear()
        if args.cmd == "workflow" or args.matt:
            try:
                errors += validate_workflow(text, path, getattr(args, "gate", "entry"),
                                            require_loads=args.cmd != "brief",
                                            receipt=args.cmd == "receipt")
            except (OSError, ValueError) as e:
                errors.append(f"{path}: invalid Workflow record: {e}")
        if errors:
            for e in errors:
                print(f"error: {e}", file=sys.stderr)
            return 1
        suffix = " (record checks only; execution needs evidence)" if args.cmd == "workflow" or args.matt else ""
        print(f"ok: {args.cmd} {path}{suffix}")
        for note in READ_NOTES:
            print(f"note: {note}", file=sys.stderr)
        return 0

    return selfcheck(Path(__file__).resolve().parent / "fixtures")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
