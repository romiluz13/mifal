# The doorbell contract

A doorbell is a member's signal that attention is needed. It is one line,
and the same line serves two readers: a human watching the pane, and any
agent (or the validator) parsing it as a durable record. State transitions
observed over a transport annotate the doorbell; they never replace it.

## Shape

```
<TYPE> <task> <payload>
```

- `TYPE` — one of `DONE`, `HELP`, `HELD`, `STOPPED`, `QUIET` (uppercase, exact).
- `task` — the stable task id (`7`) or an attempt id (`7.2`). Attempt ids
  belong to corrections; ring the attempt you are closing.
- `payload` — one token or free text, per type below. Never empty.

| Type | Payload | Meaning |
|------|---------|---------|
| `DONE` | artifact path (single token, no spaces) | The return is written; read it. |
| `HELP` | the reason (free text) | Blocked with a specific question for the lead, answerable by resuming with guidance. |
| `HELD` | what it waits on (free text) | Blocked on an approval that belongs to the human. |
| `STOPPED` | why (free text) | Stopped per the stop rule; the writeup is in the return file. |
| `QUIET` | absolute path of the event file, `<record-root>/quiet/<id>.json` (single token) | A worker's turn ended with no report. Attention only; see below. |

**Graded stop.** Any member may halt work on evidence of damage, in rising
steps, each a normal report: concern → `HELP <why>`, uncomfortable →
`HELD <what it waits on>`, stop → `STOPPED <why>` for your own task. The lead
rejects a ring from anyone who does not own the open attempt, so a reviewer
or validator who must halt *someone else's* task rings `HELD` on its own task
with a `STOP:` prefix and the evidence, for example
`HELD 9 STOP: task 7 is rewriting the shared fixture; evidence in .team/tasks/9.md`.
That reaches the human through the lead's normal `HELD` escalation. It does
not halt task 7 by itself: a cross-task STOP is not built and would need
`lead.py` support.
<!-- scar: 2026-10-16 — management research #12: stop-work authority; a non-owner's ring is rejected by lead.py, so the route is HELD with a STOP: prefix -->

For `DONE` the payload is the path to the return file and nothing else —
prose belongs in the file. For `QUIET` it is the absolute path of one event
file and nothing else. For the other three, keep the payload to one
specific phrase; the detail lives in the record.

## QUIET is attention only

No member rings `QUIET`. The team Stop hook writes one immutable event file
when an admitted Claude Code worker's turn ends with no `DONE` line, no
Return closing its attempt, and no `HELP`, `HELD` or `STOPPED`. The event's
JSON holds the owner, pane, attempt, session, reason and waiting state.
`QUIET <attempt> <event-path>` is how a lead names that event; its progress
log keeps the attempt and the path as separate fields. A `QUIET` line typed
in a pane is not a ring, and it is never delivery evidence.

- **It moves nothing.** `QUIET` never closes or fails a task, grants a
  retry or lifts a hold. It asks the lead to look at the pane and get a
  `DONE`, `HELP` or `HELD` line.
- **It outranks nothing.** The lead attends to an event only when no
  `HELP`, `HELD`, `STOPPED`, `DONE`, assignment, review or escalation is
  due. Until then, the event stays pending on the lead's attention surface,
  and it also stays pending while the lead is blocked on the human. Nothing
  is typed into the lead's pane.
- **Attendance is logged, then counted.** The lead's progress log entry
  naming the event is its consumption. Until that entry is durable, the
  event is still pending. Attending, retrying or resuming again writes
  nothing more. An attended event stays on the attention surface for one
  further turn, marked attended, because a turn killed before its reply
  loses the only other "look at its pane"; once its task has moved on by
  attempt or status, the row goes. The lead never edits or deletes an
  event file.
- **Stale events move nothing.** An event whose attempt is not the task's
  active attempt, whose task is no longer in flight, whose owner no longer
  owns the task, or whose pane is not the owner's is shown as stale. A
  session mismatch alone never makes an event stale: the session Herdr
  reports can be a child `claude` in the pane or a passing value. An event
  is superseded only by a strictly later stop or ring of the same attempt
  in the same pane from another session, whether Herdr reports a session
  or not, so each pane keeps one actionable row. Where Herdr reports a
  different session, the row names both and says to look.
- **The folder is untrusted.** Only names of the form `<64 hex digits>.json`
  are read; others are counted in one row. An event must hold exactly the
  hook's fields, `reason` exactly `no report`, and bounded ids; `init`
  refuses member names and task ids longer than those bounds. Anything
  else, unreadable files included, is a named row that echoes none of its
  text, and a human may move such a file out of `quiet/`.
- **Coverage.** Only Claude Code workers with the team Stop hook produce
  events. Other harnesses stay on the manual quiet-worker check, and a
  Stop event never claims a worker exited.

## One line, two readers

Pane-visible text a human can watch:

```
DONE 7 .team/tasks/7.md
```

The same line parsed as a record any agent can read
(`validate_contracts.py doorbell --parse`):

```json
{"type": "DONE", "task": "7", "attempt": null, "artifact": ".team/tasks/7.md"}
```

A QUIET line names the event file:

```
QUIET 7.2 /abs/project/.team/quiet/<id>.json
→ {"type": "QUIET", "task": "7", "attempt": "7.2", "event": "/abs/project/.team/quiet/<id>.json"}
```

An attempt ring parses with `attempt` set:

```
DONE 7.2 .team/tasks/7.md
→ {"type": "DONE", "task": "7", "attempt": "7.2", "artifact": ".team/tasks/7.md"}
```

## Rules

- **Write the file first, ring once.** The file is authoritative; the
  doorbell is a hint pointing at it. If the lead isn't ready within a bounded
  wait, leave the file — it stands alone.
- **The ring proves nothing by itself.** Delivery is proven by the receipt
  the ring names, never by the transport's return code. A lead that timed
  out inspects the member and the record before resending.
- **Attempt ids protect corrections.** While attempt `7.2` is open, a late
  `DONE 7` closes nothing.
- **Small messages stay small.** The doorbell is the whole signal: status,
  task id, and the path or one phrase. No reports in the pane.

Fixtures: `scripts/fixtures/doorbell/` (good and bad lines).
