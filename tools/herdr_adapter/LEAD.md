# Lead turns (spec 0001, ticket 06)

`lead.py` takes one JSON command and returns one JSON result, using the adapter's
`{"ok":true,"result":…}` / `{"ok":false,"error":…}` envelope. It exits after one
turn. It does not spawn members, schedule itself, switch models, execute task
commands, or call an LLM. Run it from the lead's pane.

Python 3.10+, standard library only. The relative skills tree must contain
`team-lead/scripts/{validate_contracts,check_compliance}.py`; these are imported
directly, not reimplemented. No network installation.

## Resume before another lead turn

After compaction, a break, or a restart, run **`resume.py` before `lead.py`**.
Use the original record root, socket path and adapter state directory. The
command is POSIX/main-thread only (its deadline uses `SIGALRM`).

```sh
python3 "$HOME/.agents/mifal/tools/herdr_adapter/resume.py" <<'JSON'
{"command":"resume","params":{
  "record_root":"/absolute/project/.team",
  "resume_id":"return-2026-10-05-a"
}}
JSON
```

Keep `resume_id` stable when recovering this invocation. A new inspection, after
new evidence or a later break, gets a new **resume** id, never a replacement
**dispatch** id. The JSON envelope matches `lead.py`; `ok:true` may contain a
HOLD. Read `handoff`, `first_action`, `outcome`, and each `plan` row.

The returning lead reads its `lead-state.json` team index, then only the active
attempt's `dispatches/<namespace>-<attempt>/record.json`, assigned return, and
named claim sidecars. It takes one fresh `observe` picture. `last_watch` is not
an identity cache: event-loop pictures are observations, not delivery proofs.
Passive visible output is read once per inspected member only when a durable
closing receipt is absent. No directory crawl, transcript history, polling,
model invocation, or member recruitment occurs.

| Classification | Trigger |
| --- | --- |
| `completed-and-reported` | Recheck the accepted receipt and current sidecar digests; HOLD on a failed recheck. |
| `completed-unreported` | Validate exact active `Closes`, unchanged brief, claims and sidecar digests through the existing lead checker. Accept one checked return; never dispatch it again. Pane-only DONE is evidence to HOLD, not acceptance. |
| `sent-unverified` | A reserved prepared/sent/refused/uncertain dispatch, in-flight task line, or current/remembered ring still has no valid receipt. Inspect once, then HOLD; no automatic retry. |
| `never-sent` | Queued task, no dispatch reservation, return, sidecar, current/pending ring or delivery memory, and an inspected idle/done member. Dispatch at most one eligible task, using the existing compliance and draft guards. |
| `ambiguous` | Identity mismatch, corrupt/missing evidence, unclosed artifact, busy member, or explicitly held/refused/stopped task. Record the reason and HOLD. |

A dispatch record's full historical identity and the team roster are compared
to the **current** pane and agent: pane/workspace/tab ids, terminal id, cwd,
agent kind and name (including null names). Regressed dispatch sequence pins
also refuse. A new queued member can be enrolled from the live identity;
in-flight work without a historical pin cannot. `send_task` carries that identity
through its shared `DispatchClient`: every guard snapshot and the final
pre-send snapshot must match. A replacement visible at those checks refuses.
This is **best effort, not atomic**: the final snapshot and `pane.send_input`
use separate socket requests. Replacement or human input after the last check
can race the send. No close operation is exposed.

Each task's `delivery_observed` map in `lead-state.json` retains rings by exact
attempt id. Current-owner pending rings count even after they leave the viewport.
Resume persists newly observed rings before continuing inspection, so changing
resume ids, clearing the screen, or exhausting a later budget cannot turn that
attempt back into `never-sent`. Remembered DONE requires receipt checks, not
acceptance or resubmission. Only a separately authorized new attempt has separate
delivery memory.

Any unresolved row, pending human escalation or exhausted budget prevents a new
dispatch. Otherwise checked reports precede assignments; eligible assignments
use the existing value ordering and accepted prerequisites. The one action uses
the existing lead receipt checker or compliance-gated `send_task`; M1 does not
start a correction attempt on its own. Even a valid late receipt cannot override
an explicit held/refused/stopped decision.

### Human answers while holding

A waiting escalation takes a file-only branch: resume journals one
`human-answer` action instead of inspecting members. It reuses the lead's closed,
typed human-answer validator, exact escalation-id check and member answer-file
writer. No socket call, prompt, model change, hiring or additional authority
occurs. Missing answers return `wait-human`; malformed/misfiled answers HOLD.
The existing task/read/byte/deadline budget bounds this branch too.

Record the human response with `lead.py`'s `answer` command, then run resume with
a **new resume id** to process it. Continue writes `answers/<attempt>-human.md`
and marks the escalation answered; stop preserves a stopped task. Both leave
the dispatch latch on. A later fresh resume must reconcile delivery/receipts
before normal lead turns can resume. Replaying the answer's resume id is inert.

### Bounds and durable first action

Defaults: **5s inspection**, **32 tasks**, **8 pane reads**, **128 disk read
attempts**, **8 MiB disk/output bytes**, **2 MiB per disk file**. The first five
are closed JSON params (`deadline_seconds`, `max_tasks`, `max_pane_reads`,
`max_disk_reads`, `max_bytes`): positive finite values only; integer counts.
Maximum deadline is 60s; maximum counts/bytes are four times their defaults.
Missing files consume read attempts. Nonregular files and symlink escapes
refuse. Receipt verification runs against bounded immutable local copies.
Pane reads count the whole NDJSON response, including escaping/envelope bytes.
Each socket receive is capped by the remaining allowance, plus one overflow
probe byte; an oversized frame closes immediately, before JSON decoding or
waiting for its newline. The authoritative snapshot remains separately bounded
by the adapter's 16 MiB response ceiling.

At a count or time cap, stop inspecting, record `inspection_error`,
`uninspected_tasks` and measured usage, and HOLD without a send. A signal
deadline also interrupts stalled/trickling socket reads; no retry loop extends
it. Local fsynced journal/projection writes follow the inspection budget.
Failure to load the bounded team index or prior journal returns a JSON refusal
instead; an independent `.resume-latch` remains HOLD even if the old index says
ready or is unreadable. A `lead-state.json` that is not a JSON object with the
index containers `init` wrote refuses with `record_corrupt` before any socket
work, in `lead`, `answer` and `resume`; resume keeps the fresh latch, so nothing
dispatches. Recovery: restore the index from a saved copy, then run resume with
a new `resume_id` (a successful fresh resume releases the latch), or start a new
authorized mission with a new record. Human-answer budget failures appear in `outcome.code`.
An authorized first dispatch has a **separate 90s action cap**; its production
60s idle / 10s empty-read guard is not shortened to fit the inspection budget.
Only disposable fixtures shorten guard timings.

`resumes/<resume_id>.json` stores the plan, single first action and its outcome.
`lead-state.json` holds a `resume_gate`; `state.md` points to the first action.
The shared nonblocking lead lock serializes writers. Under that lock, resume
fsyncs `.resume-latch` **before loading the index or prior journal**; ordinary
lead turns check its presence before loading the index. After a successful load,
the index gate mirrors HOLD; the action is journaled as `started` before effects.
Repeating a finished id returns its result without another member inspection or
send. A started or interrupted id becomes HOLD without replaying its action; a new bounded
inspection can discover a receipt or reserved dispatch. A superseded id cannot
release a newer gate. A finished successful journal cannot clear a latch that
already existed on entry: run a new inspection. Only after persisting a
successful fresh reconciliation is the latch removed and its directory fsynced.
An unchanged successful-id replay preserves readiness only when no latch existed
on entry. There is no cross-file transaction or automatic retry.

`handoff:lead` permits the next normal bounded lead turn (including `watch`).
`handoff:hold` blocks `lead.py` before any socket call. Inspect the recorded
reason and obtain the missing receipt or explicit lead/human reconciliation;
do not erase dispatch evidence, change identity pins, or clear the gate merely
to retry. Processing human-answer files does not itself resolve an ambiguous
dispatch or authorize a new model/member. Direct adapter callers still carry
their own M1 obligation; this gate is not a security sandbox.

```sh
cd "$HOME/.agents"
python3 -m unittest discover -s tools/herdr_adapter/tests -p test_resume.py -v
python3 tools/herdr_adapter/tests/live_resume.py --live
```

The live test creates only its own two-pane `ADAPTER-RESUME-TEST-*` workspace
and reuses the zero-LLM counter fixture. It proves an inspected first dispatch,
unreported completion without redispatch, identical first-action replay, a
synthetic old-server identity rejected against a real live pane, a budget HOLD,
and handoff to normal lead/watch turns. It never restarts the user's server.
The printed `/tmp/adapter-resume-live-*` directory retains exact commands,
wire requests, team records, summary, workspace/identity/focus before-and-after
proof, and fixture PID termination evidence. Scratch records are not committed
to the production team tree; production record commits remain caller-owned.

## Initialize a trusted, already-authorized mission

`init` takes `record_root` (new empty absolute directory), `project_root`
(absolute directory containing the governing `AGENTS.md`), `workspace_id`,
`lead_pane_id`, `mission`, `members`, and `tasks`. The lead requires a distinct
pane. Every member has `name`, explicit `pane_id`, and the adapter's verified
`input_box` profile. Live identities are captured on first look and compared on
subsequent turns.

Example task in the `tasks` array:

```json
{
  "id": "7",
  "owner": "normalizer",
  "why": "A checked deduplicated contact list.",
  "outcome": "Write normalized names to tasks/7/result.txt.",
  "value": 100,
  "claims": {
    "artifact": {
      "path": "tasks/7/result.txt",
      "sha256": "<64 lowercase hex digits from the agreed expected bytes>"
    }
  },
  "stop_rule": "Stop after two attempts; write an honest return.",
  "planned_commands": [],
  "files_changed": ["tasks/7/result.txt"],
  "help_answers": {
    "duplicate policy": "Deduplicate after trimming and lowercasing; sort names."
  }
}
```

The digest placeholder is intentionally not runnable. The complete executable
mission builder is `tests/live_lead_loop.py`. Optional fields:

- `after`: prerequisite stable task ids; default none.
- `required`: whether this task gates mission success; default true.
- `requests`: human questions, each with `question` and `recommendation`.
  These supplement (never replace) the actual HELP/HELD blocker in the batch.

`init` also accepts an optional `wake` object, `{"mechanism": "<string>",
"deadline_seconds": 60-3600}`, naming what starts the next lead turn and how
late that may be. It is stored in `lead-state.json` and rendered in `state.md`;
nothing here schedules the turn (see "Current state, identities and the wake").
Unknown keys, a non-string mechanism or a deadline outside 60-3600 refuse as
`schema_invalid`.

### Matt engineering tasks

Select `workflow.methodology: "matt"` (aliases `ask-matt` and `matt-pocock`
canonicalize to Matt). Supply `phase`, `skills`, `route`, `next_gate`, `start`,
`ddd`, `ux`, and `state` in that workflow object. `state` is the absolute path
to the existing authoritative parent note with its ordered phase checklist;
it must exist before init and remain available on resume. Keep one tracker.
`start` is the fixed commit or content identity accepted by the shared checker.
`skills` includes the canonical Engineering Workflow and Ask Matt bodies plus
the assigned phase procedure. The brief derives `Executor` from the task owner.
Optional `scheduler` and `integration_owner` retain their existing meaning.
Optional `attention_minutes` (a positive number, default 10) is read only by
the lead's attention rows; the brief's Workflow section never carries it.
For build/fix preparation, pass optional `grilling` with the parent's accepted
scope/design artifact and digest (or the current interview disposition). The
existing Matt gate holds implementation without accepted evidence; the brief
forwards it without asking each worker to repeat the interview. The parent's
final workflow check owns Retro, separate from worker-receipt acceptance.
Optional `route_decision` (Ask Matt's multi-session branch, as the
`Route decision:` line reads) and `cut` (one `<steps> | <the human's own words>
| <where they said it>` line, or a list of them) are forwarded into the brief
as `Route decision:` and `Cut:` lines, each one line; the existing checker
judges them at init, so a branch with no reason or unpinned outputs, or a cut
with no quote and source, refuses before any record exists (`contract_invalid`).
A multi-line `route_decision`, `cut` entry or `grilling` is refused
(`schema_invalid`), and a non-Matt workflow takes neither key. A relative Cut
source resolves from the folder of the file that holds the Cut line: the brief
(`<record_root>/tasks/`) for a `cut` given here, so give an absolute path or a
non-path pointer; the parent State's folder for a Cut the lead keeps in the
State. A source file over 2 MiB is refused with the validator's one message, in
the parent gate as on its command line. A worker's receipt honours a sourced Cut
the same way: under a cut of its Grilling, implement/tdd or code-review minimum
it is accepted without that line or body, and without the cut it is held
(`receipt-pending`). The lead's own parent record meets the same rules at its entry,
review and accept gates: a required step missing from its Phase checklist, or a
`Loaded:` read stamped after its phase's `Check: start`, holds dispatch or
completion (`parent_gate`, `completion-refused`) until the step is done or the
human's `Cut:` is recorded there.

The existing `validate_contracts.py` Matt preparation gate runs before init
writes any mission record and again before dispatch. Acceptance runs its worker
receipt check over the current full brief/return and requires current-body
`Loaded: <path> | <executor>: sha256:<digest> <read evidence>` records. Workers
record their actual complete reads; a lead cannot manufacture them. Missing or
changed reads hold the receipt without redispatch. Resume uses bounded readers
for the additional procedure bodies and parent note, resolving relative skill
paths against the original assigned brief. Matt acceptance starts a fresh
recheck under the same configured read/byte/file/deadline limits, reported as
`action_budget`; inspection evidence cannot bypass that recheck. Generic/other-owner tasks
retain the old contract; old incomplete Matt missions refuse until explicitly
reconciled, rather than silently inventing their missing decisions.

Dispatch delivers the selected procedures before it writes a Matt brief. Each
`skills` body is copied byte-for-byte into `tasks/<attempt>/delivery/`, beside a
read-only `manifest.json` recording selected path, resolved path, SHA-256,
bytes and copy. The brief lists them under `## Delivered procedures`. Only
selected bodies travel; select dependencies explicitly. A missing, nonregular,
non-UTF-8 or oversized body (2 MiB each; 8 MiB and 128 bodies total) refuses with
`procedure_unavailable` before any brief or send. After a crash, a
byte-identical packet is reused; a differing, nonregular or oversized one
refuses with `delivery_mismatch`. Both newline forms are compared as bytes;
the manifest is read separately, so replay keeps the same body limits. Delivery proves which bytes the lead supplied, not that
the worker read or applied them: workers still record their own `Loaded`
lines, and acceptance still checks them against current bodies. Generic and
other-owner tasks are unchanged.

The parent `state` record is gated in the same process. Before any Matt
dispatch writes or sends, the existing `validate_workflow` runs on it at
`entry` (or `review` when the task kind or route is review); a failure refuses
with `parent_gate` and the task stays queued. Before `complete`, every distinct
Matt parent record must also pass `accept`, so its Done means, Checks, phase
checklist and snapshot hold completion as `completion-refused`; the next turn
rechecks. Every gate read, including its Loaded bodies, Grilling/Retro/State
evidence and snapshot artifact, uses one nonblocking regular-file reader per
gate: 2 MiB per file, 8 MiB and 128 reads in total. Team Lead still chooses
each phase. These gates check the record,
not that a phase was actually performed. A Pi run keeps its native journal;
this controller only checks a file record.

This integration checks preparation, declared reads and existing artifact
claims. The parent remains responsible for actual phase advancement, pinned
reviews and final phase acceptance; it is not universal native-tool interception.

This is the ticket's deterministic tracer bullet, not general-purpose model
reasoning. The lead compares named artifact bytes to trusted, agreed digests,
or runs a verifier command named in the trusted plan; commands a member
supplies are never executed.
Help answers and staffing/model recommendations are also supplied by the
trusted lead/human plan. Unmapped HELP questions go to the human, never guessed.
Plans are **not a sandbox or authority classifier for arbitrary prose**:
authorize their scope before initializing; a gate's mechanical pass cannot
authorize a harmful task. Members retain their own safety obligations.

## Look → pick → act → record → wait

```sh
python3 "$HOME/.agents/mifal/tools/herdr_adapter/lead.py" <<'JSON'
{"command":"lead","params":{"record_root":"/absolute/project/.team","wait_seconds":1}}
JSON
```

- **Look:** adapter `observe`, scoped to the explicit workspace. Passive visible
  pane reads on first observation or changed member state/sequence. A blocked
  member or one with unfinished work is also reread once per turn: a state
  sequence does not prove its output finished rendering. No inner polling or
  focus call is added; unchanged doorbells remain deduplicated. Parse
  whole-line doorbells with the contract validator, excluding the editable
  input frame. The frame begins at a line that is exactly its start token;
  prose that mentions the token does not hide the lines below it. Resume uses
  the same parse. Read durable returns too, so a wrapped/missed DONE cannot erase
  a receipt. A socket acknowledgment or idle status never closes a task.
  Return reads are bounded, nonblocking regular-file reads (2 MiB per file). A
  FIFO, directory, non-UTF-8 or oversize return refuses only its own task
  (`receipt-refused`); other tasks proceed in later turns and the lock is freed.
- **Pick:** explicit leverage scores: HELP/HELD/STOPPED **300**, DONE **200**,
  valuable idle assignment **100**. Assignments then sort by descending `value`;
  ties retain plan order, with no polling cursor. Every result logs all
  candidates, chosen moment, and reason.
- **Act:** one dispatch, answer, review/correction, or escalation batch.
  `gate_dispatch()` receives task/member/attempt plus planned commands and paths;
  the full report and history are persisted. Tier-0 refusal sends nothing.
  Otherwise validate/write the brief, persist the task line, then call guarded
  adapter dispatch with an explicit pane and a stable namespace/attempt id.
  A lead-owned client wrapper carries the identity pinned by `look` through
  **every guard snapshot and a final pre-send snapshot**. Pane and agent must
  still match the pinned pane/workspace/tab, terminal, cwd and agent kind;
  the agent name must also match (including null). A replacement refuses before
  any send. The adapter's draft, timing and sequence checks remain unchanged.
  A final-check refusal after reservation conservatively retains an uncertain
  dispatch id; it must not be retried. A resume deadline (`resume_budget`)
  during dispatch is also uncertain, because input may already be written. The protocol still has a non-atomic
  check/send gap; this is not a server-side compare-and-send guarantee.
  The visible prompt points to the durable brief. Defaults remain 60s idle,
  10s between empty-box reads, and 500ms shell-ready delay.
- **Record:** `state.md`, `agreement.md` v1, people ledgers, `lessons.md`,
  `decisions.md`, task briefs/returns and sidecars. `lead-state.json` is the
  lead-owned restart index; `state.md` is its human-readable projection, and
  its first section, `## Current state`, is generated by this same writer on
  every record (below). Nothing else writes `state.md`.
  Per-record nonblocking lock serializes lead/human-answer writers; `init`
  checks that the record is empty (apart from `.lead.lock`) under it. Atomic
  writes use the adapter's fsynced writer. There is no cross-file transaction:
  a crash after preparation requires reconciliation, not a blind retry.
- **Wait:** event-loop `watch` runs with a positive limit (default 1s, maximum
  60s); its subscription/floor/watchdog diagnostics go to stderr and its final
  picture/stats into the record. The next turn compares authoritative sequences.
  Drain or redirect stderr. This bounded invocation does not leave a daemon.
  `lead.py` still exits after one turn and schedules nothing; `wake.py` is the
  caller-side waiter that tells the caller when to run the next turn.
  The turn's entry is recorded before the wait. If the trailing watch is
  refused (for example `observation_unavailable`), the turn still exits 0 with
  `"wait": {"error": "<code>: <message>"}` and keeps the previous `last_watch`.
  An unavailable first observation, before any action, still refuses the turn.
  A malformed event envelope, a non-object nested `pane`, or a present
  non-null non-string `pane_id`/`workspace_id` is a `transport_error` connection death:
  the watch reconnects within its retry bound and deadline instead of raising.
  Lifecycle events that omit either id remain valid. Other event fields are not
  schema-validated here.

`done` is herdr's idle-but-unseen state. Both picker and adapter treat it as idle,
without focusing a pane. Provenance: protocol-22 research
`~/Dev/herdr-socket-proto/research-socket-api.md`, §1.5, and the live fake's
snapshot-confirmed `reported_state: idle` → `state: done` oracle.

## Receipts, corrections and human authority

DONE must name the assigned record-internal return file; symlink/traversal
escapes are refused. First verify the unchanged lead-owned brief prefix, then
validate and extract receipts **only from the appended member suffix**.
Disk-based DONE discovery uses that same suffix boundary: a receipt example
in a brief is never a member return. The suffix must close exactly the active
attempt once, with no additional task closures.
Every named claim must pass at the **actual sidecar SHA-256**, which
the lead independently compares to the agreed digest. All accepted artifacts
are rechecked before mission completion.

A **verifier claim** replaces `path`/`sha256` with
`{"check": [argv...], "timeout_seconds": n}`, where 0 < n ≤ 600, in the init
plan only. The lead runs that argv in `project_root` with no shell, closed
stdin and output captured to a temporary file. It records the exit code,
duration and output digest in the review proof. The member must still report
the claim `passed`. Exit 0 passes; a nonzero exit fails the claim and takes
the correction path.

**Checker identity.** At init the lead resolves `argv[0]` once, against the pinned `project_root` (the directory the
check runs in), and pins the sha256 of that file and of every other argv element that is an existing regular file,
absolute or relative to the pinned `project_root`. A name with a slash is taken relative to `project_root`, and so is
every relative or empty `PATH` entry, whatever directory the lead itself was started in. An `argv[0]` that resolves to
no executable file is refused at init (`schema_invalid`). The pinned absolute path is stored in the plan; before it
runs a check the lead rechecks every pin and then launches **that stored path** (`argv[1:]` follow), so the file it
identified is the file that runs and `PATH` is not consulted again. The stored path is named as it was named: only `.` and empty
components (repeated slashes) are dropped, and every `..` and symlink stays, so the stored head can contain `..` and the
operating system resolves it exactly as it resolves a direct run (`link/..` is the parent of the link's target); a venv's
`bin/python`, a `bin` that is itself a symlink and `bin/../bin/python` all keep their venv. The one gap left is a checker
replaced after the final recheck and before it is launched by a process of the same user racing the launch, which macOS (no
`fexecve`) gives no way to close. A missing or changed file, or a record with no
pinned executable, leaves the claim **unverified, not failed** (`verifier_unverified`): a DONE turn escalates and the
task is `held`, never accepted. The check's `argv[0]` is launched as that absolute path, so a checker that reads its
own `$0` sees the path rather than the bare name. The supported form is *a
checker script named by path*. Not pinned: directories, module names (`-m x`), files the checker opens itself
(a library, its inputs), and the interpreter a script's `#!` line names (`#!/usr/bin/env python3` looks up `PATH`
when the script starts; prefer `[<absolute interpreter>, script]`, which pins both). A file over 512 MiB cannot be pinned and refuses the plan at init. Two consequences: a
pinned file that the work itself legitimately rewrites (a test file the worker must edit, a build output named in
argv) will hold the task, so name only fixed checker files in argv; and a checker that was changed on purpose needs
a new plan, because a human `continue` re-reviews with the same pins and holds again. Upgrading the interpreter
that `argv[0]` names holds the tasks that pinned it.

A timeout or a command that cannot start leaves the claim **unverified, not
failed**:
- a DONE turn escalates to the human and the task is `held`;
- a human `continue` re-reviews the unchanged receipt;
- closing returns `completion-refused` and rechecks on the next turn;
- the resume accept action holds.

When another claim's verifier exited nonzero in the same review, that known
failure takes the correction path, and the unverified claim is listed with it.

Resume inspection never runs verifiers. Its accept action runs them after the
bounded recheck, under each verifier's own timeout. A timeout kills the
verifier's process group. Descendants that outlive a normal exit are not reaped.

A verifier runs as the lead, with the lead's environment, on project files the
member may have edited. Name checks whose inputs the member cannot rewrite, or
treat a pass as the member's tests passing. Every lead turn after `complete`
reruns all verifiers; stop the loop at `complete`. Verifier output is not
size-capped.

**Git evidence.** Dispatch records the project's HEAD as the attempt's
`git_base` before the prepared journal write. It records an `unavailable`
reason outside a git work tree. Lead turns that stop or escalate, and every
resume row for a dispatched attempt, carry a `git` window with:
- HEAD and whether the base is still its ancestor;
- the number of commits since the base, plus up to 20 SHAs.

Uncommitted work is not reported. Git's working-tree comparison runs the
repository's clean and process filters, which a member can configure. The lead
reads only refs and commits, with fsmonitor, lazy promisor fetches and replace
objects disabled.

The window is evidence only. It never changes a status, classification or
trigger, and a git failure records `unavailable` instead of refusing. The
project root is shared, so the window includes other members' and the
human's commits; attribute them from the SHAs.

Limits of the git window:
- Resume computes windows after the inspection deadline. It starts no new
  window after 10 seconds, but one window can take up to 25 seconds, so the
  git phase can last about 35 seconds while holding the record lock.
- A batched escalation carries only the ringing task's window.

Failed checks produce `7.2` with its own brief, return, dispatch id and review
proof. Old `tasks/7.md` is never overwritten. A late `DONE 7` cannot close `7.2`;
the rejection names the still-open attempt. Two failed attempts stop the task.
Incomplete/contract-invalid returns (or a not-yet-created return file) produce
`receipt-pending` and leave the task in `review-pending`, not a correction.
DONE deduplication includes the assigned receipt's content digest. A changed
revision is reviewed again, including from disk without another doorbell;
unchanged partial text is not repeatedly reviewed. No redispatch or new
attempt id is created while waiting for the suffix to finish. A
`review-pending` task whose owner stays `idle`/`done` with an unchanged return
for three consecutive turns is escalated once. The turn that set
`review-pending` counts as the first only when its owner was already
`idle`/`done`; an owner still working starts at 0. A changed return or a
non-idle owner resets the count.
A human `continue` on that stall returns the task to `review-pending` with the
count at 0, so another unchanged stall escalates again; a stale visible ring is
not new work.
Changed brief prefixes, wrong return paths, wrong closure ids and other
integrity failures remain `review-refused` for explicit reconciliation.
Guard refusals and uncertain sends are never automatically retried.
Resume keeps these outcomes: a restored receipt cannot make a `review-refused`
task accepted, and resume refuses a failed mission with `mission_failed`.
A required task that ends `refused`, `stopped` or `review-refused` records
`mission-failed` on the next turn, before any queued optional dispatch; only a
waiting human answer is handled first. Later turns refuse with `mission_failed`.
A queued required task whose `after` dependency ended `refused`, `stopped` or
`review-refused` is escalated once, naming both. Optional queued work behind
such a dependency, directly or through a chain, can never run: it becomes
`stopped` with a `not_run` reason naming the dependency, the turn lists it
under `not_run`, and `closing-checks.json` records it as not run, never
accepted. A required task behind that chain still escalates. `continue` cannot accept a
stopped dependency: the task returns to the queue and the next turn records
`mission-failed` with that reason; `stop` stops it, which also fails the
mission. Failed and refused outcomes stay terminal and there is no reset
command: reconcile through a human answer or a new authorized mission with a
new record.

HELP is answered in `answers/<attempt>.md`, preserving blocked-pane input and
human drafts. Members must observe their answer file with their brief's bound.
HELD (or unmapped HELP) creates `escalations/<n>.md`, batching current reserved
questions and attaching the lead's recommendation to each. Every triggering
HELP/HELD detail is preserved verbatim as a question with a conservative hold
recommendation; configured questions/recommendations are added afterwards,
never substituted for the actual blocker.

The human's trusted caller supplies:

```json
{"command":"answer","params":{
  "record_root":"/absolute/project/.team",
  "escalation":"1",
  "by":"human",
  "decision":"continue",
  "answer":"Keep current models and roster; continue original scope."
}}
```

`continue` means only the **original authorized scope**; `stop` stops the held
tasks. Neither grants model/hiring/destructive execution. The next lead turn
attaches the human answer to the escalation and writes member answer files
before changing any state, so a failed write leaves the batch waiting. After
`continue`, the same attempt's HELD/HELP lines are released: the old visible
copy stays suppressed while its count is unchanged, and an identical new ring
(a higher visible count, or the line returning after it left the viewport)
escalates again, including on the turn right after `human-answer`. The
baseline is the visible count read by the answering turn itself, so an
identical ring already on screen then belongs to the answered batch. A record
written before these counts were kept takes them from that same read. A line
an older lead already released with no count cannot tell a repeat from the old
copy, so it is released: it escalates once more even if unchanged, and the
next `continue` suppresses it normally.
Both the command and the on-disk answer use the closed schema
`{escalation, by, decision, answer}` with nonempty string fields, a numeric
escalation id and `continue|stop` decision. Before releasing anything, the
file's `escalation` must match the waiting batch id. A malformed or misfiled
answer returns `invalid_answer`; correct the file and retry the lead turn.
The batch and member tasks remain held, with no member answer file written.
The loop conservatively holds all new actions while a human batch is pending.
This local file seam assumes a trusted caller, not authenticated human identity
or hostile-process isolation. The record root is writable by the same user as
the lead, and trusted verifiers run in the agreed project cwd with that user's
permissions: any process running as that user can change records or verifier
inputs. This is a documented trust limit, not a sandbox.

## Current state, identities and the wake

`lead.record()` writes `## Current state` first in `state.md`, rendered from
`lead-state.json`, `reviews/<attempt>.json`, the return files and the parent
note. It is generated: the next record overwrites any hand edit, and a
projection failure writes an `UNKNOWN: projection failed` stub instead of
stopping the durable index. It holds, in order:

- the mission line, outcome, last lead turn, recorded wake, last wake and the
  parent note's phase, next gate and checklist count;
- **Lead attention needed**, one bullet per row, or `- none`:
  1. an idle or done member whose owner has an eligible queued task (the same
     rule `pick()` assigns by) while no lead turn has dispatched it;
  2. a DONE return seen but not reviewed for more than `attention_minutes`
     (workflow field, default 10) after its `returned_at`;
  3. an in-flight task whose last lead turn is older than the recorded wake
     `deadline_seconds`, or any in-flight task when no wake was recorded;
  4. an owner whose Herdr status is anything but `working` while its task is
     in flight and no return closes the attempt, more than `attention_minutes`
     after dispatch (dispatch time `UNKNOWN` also raises it). Each status the
     schema lists has its own wording: `idle` and `done` name the blind spot
     below; `blocked` says the pane waits on a dialog only a human answers
     (look at it, never type into it); `unknown` says Herdr cannot tell what
     the pane is doing; a status the schema does not list says so and asks for
     a look. An owner with no observed status yet raises nothing here. This is
     also the only place a `/clear`, a replaced session or a worker lost before
     it wrote anything becomes visible: a Stop hook cannot see those (see
     Acceptance preflight);
  5. the same for each assignment pin in `<record-root>/assignments/` (default
     10 minutes): an owner who is a member of the record and idle or done, or
     owner status `UNKNOWN` for a pane the record cannot observe; a pin that
     cannot be read is a row too, so a malformed pin is never silent;
  6. a queued dependent held by an `accepted-bounded` predecessor: `dependent N
     held by accepted-bounded predecessor M; a human decides`. The hold stays;
     this row only makes sure it cannot sit silent;
- **Outcomes**, one row per task: owner, scope (the outcome line), source
  identity (`git_base` plus digests named in the receipt's Claims), reviewed
  and installed identity, next permitted action (it says to dispatch exactly
  when `pick()` would, including the rule that an owner busy with another
  attempt is not assigned a second one), open gate and display status;
- **Attempts**, one row per attempt: dispatched, returned, accepted, time in
  review, correction rounds and human interventions.

Display statuses map the scheduler's enums without renaming them, shown as
`display [raw]`: `implemented` = accepted with a passing review proof;
`blocked-on-check` = `review-pending`, `held`, a held verifier, or a failed
completion check; `accepted-bounded` = accepted with a `bounded` identity;
`released` = accepted with an `installed` identity, and `released (bounded
scope)` when that attempt also has a `bounded` identity (installation is a
separate fact from full coverage, so the bounded gate text and the note naming
where the excluded scope is recorded stay in the open gate); any other status
is shown raw. An installed identity with no `reviewed` identity on the same
attempt keeps its status and adds the gate `installed without a recorded
review`. Missing or contradictory input renders `UNKNOWN [raw]` and names the
gate: an accepted task whose review proof is missing, has errors, or names a
different attempt or receipt than the task's active attempt and assigned
return; a recorded identity whose evidence file is missing, moved outside the
record roots or no longer has the sha256 stored when it was recorded (gate
`evidence missing or changed`); or an installed identity on work that was never
accepted. The same proof match decides whether `accepted` is shown in the
Attempts table. The scheduler's enums are untouched, so a stopped, refused or
review-refused required task still fails the mission and never releases
dependent work. Only an `accepted` task with no `bounded` identity on its active
attempt releases a dependent (`pick()`, the attention rows, the projection and
`resume.py`'s dispatch plan share that one rule, `lead.satisfied`): a dependent of an `accepted-bounded` task stays queued and
its gate reads `waits on 7 (accepted-bounded)`. **Limit:** no command lifts that
hold, and no attention row or escalation announces it; a human decides whether
the recorded scope covers the dependent and starts a new mission.

Measurement is per attempt and only what the record holds. `dispatched` and
`accepted` come from the existing progress entries and review proofs;
`returned` is the return file's mtime when `look()` first saw a matching
`Closes:` suffix and is set once, so a member rewriting its return later does
not move it (mtime also changes if a member's tooling touches the file before
the lead's first look, which this cannot tell apart). A return that cannot be
judged (the member changed the brief prefix, or the file is unreadable) still
goes to review and is refused there, but leaves `returned` `UNKNOWN`; only a
matching `Closes:` suffix actually seen sets it. `time in review` is
accepted minus returned; correction rounds come from the attempt suffix;
human interventions count answered escalations naming the attempt. A task
accepted through `resume` rather than a lead turn has no `returned`, so its
time in review is `UNKNOWN`. Costs and any other figure are never estimated.

The one extra command records an identity and nothing else:

```json
{"command":"record","params":{
  "record_root":"/absolute/project/.team",
  "task":"7", "attempt":"7", "by":"lead", "kind":"reviewed",
  "identity":"<64 lowercase hex digits, or a 40 digit commit>",
  "evidence":"reviews/7.json"
}}
```

`kind` is `reviewed`, `installed` or `bounded`; `by` is `lead` or `human`.
`evidence` must be an existing regular file (at most 2 MiB) under exactly two
roots: the record root and its parent directory. The directory of the task's
`workflow.state` note is not a root, so pointing that note elsewhere grants
nothing. Anything else is `path_outside_record`, and a missing file is
`evidence_unavailable`. An unknown task is `unknown_task`, an attempt that is
not `<task>` or `<task>.<n>` is `attempt_mismatch`, and an attempt that does
not exist for that task is `unknown_attempt`: the existing attempts are the
first one, the active one and each correction the lead created, so a rejected
doorbell or an earlier record cannot create one, and a record cannot be made
ahead of a later attempt. It runs under the record lock, appends `{kind,
attempt, by, identity, evidence, evidence_sha256, at}` to `tasks[id].identities`
(the sha256 is of the evidence bytes at record time), and re-renders
`state.md`; recording the same entry again returns `already-recorded` and
writes nothing. Every render re-reads the evidence: a missing file, a file that
moved outside the roots, or different bytes turns the outcome `UNKNOWN` with
the gate `evidence missing or changed` until the evidence is restored or the
identity is recorded again with current evidence. The check and the read act on one object: the
evidence is opened once without following a final symlink and its real path (from the open descriptor)
must still be under the two roots, so a path swapped for a symlink, or a directory swapped for one,
after the containment check renders `UNKNOWN` instead of the digest of another file. The latest entry per kind for
the active attempt is the one checked and shown. A recorded identity is a human
or lead claim bound to evidence, not something this command verifies.

### Wake

`wake.py` is a bounded caller-side waiter, run by whoever runs the lead turns
(the lead pane), between turns:

```sh
python3 "$HOME/.agents/mifal/tools/herdr_adapter/wake.py" <<'JSON'
{"command":"wake","params":{"record_root":"/absolute/project/.team","max_seconds":600}}
JSON
```

`max_seconds` is required (above 0, at most 3600); optional `slice_seconds`
(default 10, at most 60) is the length of each observation. One invocation:
first checks the assigned return files, then repeats `event_loop.watch` for
one slice at a time (so the existing loop is reused, not a second subscription
loop) and compares each final picture with what the lead last saw (its last
`last_watch` picture, else the signatures its last look read). It exits 0 as
soon as it finds a change, with
`{"reason": "new_return" | "pane_status" | "deadline", "changes": {"panes": [...], "returns": [...]},
"journaled": true|false, "waited_seconds": n}`. `new_return` means a return file
closes an in-flight attempt at a revision whose DONE the lead has not queued
(the same key `look()` dedups on), whether or not any doorbell or pane
transition happened. `pane_status` lists each member whose
`state_change_seq` or `agent_status` differs. `reason` names the first of
those in that order; `changes` lists everything found. A pane change is seen
within one slice; a return already on disk is seen at once.

It journals `last_wake` (`at`, `reason`, `changes`) in `lead-state.json` under
the record lock. If a lead turn holds the lock the wake is still reported with
`"journaled": false`. `state.md` shows the entry after the next lead turn. It
never sends input, reads a pane, dispatches, answers or accepts: its only
writes are that journal entry. A refused observation (for example
`observation_unavailable`) exits 1 with the error, so a failed wait is never
mistaken for a quiet one. The caller then runs one lead turn; the lead should
not end a turn without a wake source.

Restart is unchanged: `resume.py` reconciles existing returns before any
waiting, accepts a checked receipt and never redispatches. A receipt-only
completion with an unchanged pane status and no doorbell is found by `wake.py`
as `new_return` and, after a lost lead, accepted once by `resume`.

### Wake without a lead record (the manual path)

A round run without `lead.py` has no `lead-state.json`. `wake.py` then takes
`returns` instead of `record_root`: at most 32 items, each `{"path": <absolute
path of an existing file>, "attempt": "<task>" or "<task>.<n>"}`, plus
`max_seconds` and optional `slice_seconds` as above. `record_root` and `returns`
are exclusive; giving both, or neither, is `schema_invalid`, as is any malformed
item, before any socket call.

```sh
python3 "$HOME/.agents/mifal/tools/herdr_adapter/wake.py" <<'JSON'
{"command":"wake","params":{"max_seconds":600,"slice_seconds":10,
 "returns":[{"path":"/absolute/tasks/1.md","attempt":"1.2"}]}}
JSON
```

It exits `new_return` when a listed file's own text carries a `## Return`
section whose `Closes:` line names the listed attempt, including one already
on disk when the wait starts, so list only the returns still awaited; `changes.returns`
holds `{path, attempt, sha256}`. With no lead record the lead-owned brief prefix
is not known, so the file's own frontmatter must name the attempt (its `attempt:`
field, else `task:`); a file whose frontmatter names another attempt, or has
none, is refused with `receipt_mismatch` (exit 1) rather than waited on. The
brief's own `## Return` instructions, an earlier attempt's `Closes:`, and a Markdown
example of a receipt inside a code fence (``` or ~~~) do not match. It reads and journals no lead record (`"journaled": false`) and, without
`workspace_id`, makes no socket call at all: it only re-reads the files once per
slice. With `workspace_id` it also watches that workspace one slice at a time
and reports `pane_status` for any pane whose `state_change_seq` or
`agent_status` differs from the first picture of this wait (every pane in the
workspace is compared, including the caller's own, since no member list exists;
a change during the first slice is not seen). It still never sends input, reads
a pane, dispatches, answers or accepts.

What this proves and what it does not: the unit tests prove the waiter exits
`new_return` when a listed file gains a matching suffix mid-wait, at the
deadline, and on a malformed list. That a lead's next turn then actually starts
and acts on the receipt is the caller's behaviour, not the waiter's: it is
proved only by the lead's live dogfood after install (run the waiter, let a
worker close its return with the pane status unchanged and no doorbell, and
check that the lead's next turn reviews it within the deadline). It is not a
unit claim.

### Acceptance preflight and Stop feedback

`preflight.py` is a read-only look at a worker's return, so the worker can be told what is missing before it stops.
It is feedback. It accepts nothing, writes nothing and runs no verifier; `lead.py` and `resume.py` never read its
output, and the lead still accepts only through its own check (`lead.review_receipt` with the plan's verifiers).

```sh
python3 "$HOME/.agents/mifal/tools/herdr_adapter/preflight.py" <<'JSON'
{"command":"preflight","params":{"record_root":"/absolute/project/.team","pane_id":"w2X:pG"}}
JSON
```

Params: `record_root` and `pane_id`, or an explicit `{return, attempt, matt}` triple (an absolute path, `<task>` or
`<task>.<n>`, a boolean) and nothing else. A malformed request exits 1 with `schema_invalid`. Every other outcome
exits 0 with one typed verdict:

| verdict | meaning | fields |
|---|---|---|
| `preflight-ok` | nothing the preflight can see is missing | `source`, `attempt`, `return`, `closes`, `dispatched_at` (a pin only), and for a lead.py task `task` and `claims` |
| `missing` | the worker can fix this | `errors`, the precise list, and the same identifying fields |
| `cannot-evaluate` | the preflight cannot judge | `reason`, `detail` |

`closes` is true when the return file already holds a Return section that closes this attempt, valid or not.
`dispatched_at` is echoed from the pin as written; no freshness rule is applied to it.

`cannot-evaluate` reasons: `unassigned_pane` (no member and no pin), `nothing_in_flight`, `record_corrupt`,
`record_unavailable`, `pin_invalid`, `return_unreadable`, `evaluation_failed`, or the code of an unexpected
refusal. `preflight-ok` is not acceptance: a task whose plan verifier would fail or time out is still
`preflight-ok`, and the lead's turn then fails or holds it as before.

**Binding.** The pane is the key: `HERDR_PANE_ID` plus the record root, which is fixed in the hook command.
- *A lead.py record.* The member on that pane and its task in flight (`dispatching`, `sent`, `uncertain`,
  `help-answered`, `review-pending`). The attempt is `task["active"]` from `lead-state.json`, never from the session.
  `lead.review_receipt(..., run_checks=False)` is the only claim evaluator: brief prefix unchanged, the receipt
  contract (with `--matt` rules for a Matt task), exactly one section closing this attempt, and every claim
  (artifact digests; a verifier claim must be reported `passed`, but is not run).
- *The manual path (no `lead-state.json`, or a pane that is not a member).* The lead writes one pin per dispatch,
  `<record-root>/assignments/<pane-id>.json`:

  ```json
  {"return":"/absolute/path/to/tasks/4.md","attempt":"4","matt":true,"dispatched_at":"2026-10-16T16:12:41+00:00"}
  ```

  It is the dispatch record the manual path lacks, not a tracker. The lead writes the pin, or atomically replaces it,
  when it dispatches, and removes it at acceptance, cancellation or reassignment of the pane. A completed pin is not
  evidence of a current task: one left behind keeps yielding `preflight-ok` for a finished return, and one not
  replaced at the next dispatch gives feedback about the wrong task. The pin's `attempt` must equal the attempt of
  the doorbell the worker will ring. All four fields are required. The same record has no claim set, so the return is
  checked against itself: its frontmatter `attempt:` (else `task:`) must name the attempt, exactly one `## Return`
  section outside code fences must close it, and `validate_contracts` receipt (with `--matt` when `matt` is true)
  must pass. The explicit triple does the same without a pin.

**Limit, the brief the lead did not write.** On the manual path the lead-owned brief prefix is not known, so a
self-consistent return that the worker wrote or edited gets `preflight-ok`. That is acceptable only because nothing
accepts on it. The lead's own receipt check and review are what accept.

**Hook.** `hooks/team-stop.sh <record-root>` is a template for a project's `.claude/settings.json` (see
`hooks/settings.example.json`, `timeout` 20). Installing it is an integration step. Order: no `HERDR_PANE_ID`, no
record, or `stop_hook_active` true exits 0. Claude Code fires Stop at every turn end, so the hook gives feedback
only when the worker claims completion: any line of the last assistant message that starts `DONE <attempt>`, with
optional `.`, `,`, `:`, `;` or `!` after the attempt (`DONE 9.` and `DONE 9.2.` are claims), or a return file that
already holds a Return section closing the attempt (`closes`). One line naming the pane's attempt is enough: other
`DONE` lines that name other attempts, such as a quoted earlier completion, do not cancel it. A last message whose
first word is `HELP` or `HELD` always exits 0, so a question for the lead is never blocked. A first reply, a
mid-task pause and any other stop exit 0 silently. When `DONE` lines name only other attempts (`DONE 8` on a pane that
is on attempt 9), the hook exits 0 and logs an `attempt mismatch`.
For a claimed completion it runs the preflight and maps the verdict, never forwarding an exit status:

| preflight verdict | hook exit | the worker sees |
|---|---|---|
| `preflight-ok` | 0 (2 once if the Stop payload lists `background_tasks`) | nothing (or the background-task note) |
| `missing` | 2 | the error list on stderr |
| `cannot-evaluate`, a crash, no JSON, a missing interpreter or script, an unknown verdict | 0 | nothing; one line in `<record-root>/stop-hook.log` |

The hook never exits 1 (a non-blocking error), never runs a plan verifier, and writes only `stop-hook.log`. Use an
absolute interpreter in `TEAM_STOP_PYTHON`, not a version-manager shim; without it the hook uses `/usr/bin/python3`.

**What a Stop hook cannot do, observed on Claude Code 2.1.301** (`tasks/4/probe-results.md`): a project Stop hook
loads under a custom `CLAUDE_CONFIG_DIR`; exit 2 blocks the stop once and the model is shown stderr;
`stop_hook_active` is true on the next Stop; a missing hook script fails with exit 127 and the session still
finishes. Not verified natively: `/clear`, Esc and interrupt, interactive sessions, hook timeouts, and
`team-stop.sh` itself. A cleared or replaced session in the same pane, a worker that never stops, and an
interrupted worker produce no Stop event, so the lead learns of them only through attention row 4 or 5.
Session binding through Herdr `agent_session` is deferred: it is not shown to be populated.

## Verification and persistence

```sh
cd "$HOME/.agents"
python3 -m unittest discover -s tools/herdr_adapter/tests -v
python3 -m py_compile tools/herdr_adapter/*.py tools/herdr_adapter/tests/*.py
python3 tools/herdr_adapter/tests/live_lead_loop.py --live
```

The opt-in test creates one four-pane `ADAPTER-LEAD-TEST-*` scratch workspace:
lead, normalizer, counter, reporter. It intentionally injects one incorrect
first result, an obsolete DONE, and a model/hiring request. All agents and the
human answer are explicit deterministic fixtures: **zero LLM calls**.
The scratch-only proxy accepts only adapter methods and owned pane ids.

Proof is left at the printed `/tmp/adapter-lead-live-*` path:
`commands.json`, `turns.json`, `turn-*.ndjson`, `screens.json`, member
`states.ndjson`/`received.ndjson`, `wire.json`, `summary.json`, and `.team/`.
`workspace-{before,after}.json`, `identities-{before,after}.json`, `focus.json`,
and `teardown.json` check the original ids, labels, order, pane counts, focus,
and terminated fixture pids. Screens prove passive visible contents, not pixels.

The harness creates a **local scratch Git repository** with initial/final team
record commits and `record-git.json`; it never changes Git identity or pushes.
Production record commits remain the trusted caller's responsibility. Scratch
records stay outside `~/.agents` to avoid adding test fleet state to real
project memory. The core does not auto-commit production records.

The skill/contracts remain the binding vocabulary sources:
`team-lead/specs/0001/tickets/06-lead-loop-integration.md`,
`team-lead/specs/0001/spec.md` (lead loop/testing decisions),
`team-lead/SKILL.md` M1–M5/M9/M10, and
`team-lead/references/contracts/{brief,receipt,doorbell,team-record,compliance}.md`.
