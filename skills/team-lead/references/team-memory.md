# The team record

Read when establishing the project folder, at every cycle boundary, and on
resume. The record exists so a returning lead can make a sound next decision
without reading a conversation. It is a maintained working model, not a
transcript. The checkable shapes the record shares with members (doorbell,
brief, receipt) and the per-artifact writers are fixed in
[contracts](contracts/README.md); this file stays the working guidance.

## Adopt what exists, start small

Use the project's existing records if it has any (`.team/`, `.orchestrator/`,
a plans folder — whatever is there). Only create a folder when none exists;
`.team/` is a suggestion, not a requirement. Start with one `state.md`; add
files when separation saves rereading or prevents write conflicts. These are
roles for information, not a mandatory schema. Link existing plan, decision,
test, and issue systems instead of building a second tracker.

Native task records and Pi's existing journal may supply these roles. Name
the authoritative surface and return identifiers in the brief; keep one
task-state authority. An explicitly read-only request uses conversational
records and states their persistence limit instead of creating team files.

```text
.team/
  state.md             waiting on you, mission, roster, active work, progress log, first resume action
  agreement.md         how this team works: channel, latitude words, this project's
                       brief additions and return deviations, definition of done,
                       reserved vs authorized — versioned by retros, with scars
  decisions.md         decision · why · evidence · who challenged it · what would reopen it
  lessons.md           "When <trigger>, do <rule>" + the scar it came from
  people/<member>.md   capacity ledger + strengths + one development target + one role line
                       (accountability · must-not · escalation: who it asks, and when)
  people/lead.md       the lead's own development, fed by retro answers
  tasks/<id>.md        the brief + the worker's return
```
<!-- scar: 2026-10-16 — management research #5: role cards need a boundary and an escalation line -->

Use workspace-relative paths inside the record: paths that point into the
record itself resolve against the record root named in `agreement.md`
([communication](communication.md)), never the reader's own worktree; code
paths resolve in the worktree the brief names.

## One project, one record

Bind the folder to one project. The same member name in another project
starts with unknown capability here. Don't search, import, or merge
cross-project profiles; the skill supplies the method, not a shared dataset.
Moving records between projects takes an explicit user request.

## state.md

Keep it scannable:

- **`## Waiting on you`**, the first section, because the human reads it
  first: every outstanding human decision and hold recorded elsewhere in the
  record, one line each with the task or attempt, what is needed, your
  recommendation, its source and the original waiting-since time, or the
  single word "nothing". Seeing an item again never resets its age or starts
  another escalation.
- Mission and the finish condition (stated so it can pass or fail).
- The authority boundary — reserved for the human vs pre-authorized — as
  recorded in `agreement.md`.
- Roster: member, pane, agent kind, session id, role, current ownership.
- Active work: outcome, owner, latitude, expected time, return path.
- Progress log: append-only one-liners with evidence, pruned at milestones.
  This is what the human reads; keep it current and honest.
- The single first action on resume.

The lead owns the shared summary. Workers own their task notes and may
propose changes; coordinate writes so nobody overwrites current state.

## agreement.md, decisions.md, lessons.md

`agreement.md` is standard work: the channel and doorbell format (the
vocabulary itself is fixed across projects by the
[doorbell contract](contracts/doorbell.md); the agreement names this
project's channel), the latitude words, this project's additions to the
brief and return contract (the full templates live in
[communication](communication.md)), the definition of done, and what's
reserved for the human versus authorized without asking. It also names the team record's root (absolute path):
record-internal paths resolve against that root, never the reader's
worktree, while code paths resolve in the worktree the brief names. Retros
propose changes to the **process** fields; apply them only within explicit
authorization for durable rules. A change to how the
team works is a diff here, not a sentiment. The authority boundary itself
(reserved versus authorized) changes only with the human: a retro works
within existing authority and never expands it.

The authority section also holds the **Consult matrix**: how much the human
wants to be consulted in each phase of the route. Ask once at project start,
as one question with a recommended matrix, and record the actual answer on
one line. The recommended starting matrix:

`Consult: scope: high; research: low; resolve design: high; plan: low; build: low; review: low; verify: low; retro: low; default: low`

- **high:** consult on material design choices and at every phase checkpoint.
- **medium:** agree scope and design and review milestones; delegate routine
  in-scope choices.
- **low:** agree outcomes and authority once; consult only on exceptions and
  on reserved or unsettled choices.

The default fills any phase left unset. With no matrix recorded, say so, keep
doing reversible inspection, and hold new material choices that lack
authority. Consultation never expands authority: reserved actions and plan
acceptance always go to the human at every level, and confidence is not a
grant. When a change comes from a
failure, add a one-line scar comment saying what happened.

`decisions.md` holds the accepted decisions with their why, evidence, who
challenged them, and the fact that would reopen them. A decision with no
reopen condition looks more certain than it is.

`lessons.md` holds rules that change future work: "When <trigger>, do
<rule>", plus the incident it came from. Record only lessons that change
work; merge near-duplicates and retire dead ones at milestones. Workers
propose lessons in their returns (`Lesson proposed:`); the lead checks one
against the evidence before it becomes a team rule. A short-lived worker
gets a task return, not a career file.

## The task file

`tasks/<id>.md` carries the brief and, below it, the worker's return in the
shape the return contract in [communication](communication.md) defines:
claims with status and the revision checked, what the brief should have said,
any proposed lesson. One file per task; the detail lives here, not in
messages. The checkable shapes are the [brief](contracts/brief.md) and
[receipt](contracts/receipt.md) contracts;
`scripts/validate_contracts.py` verifies them.

## The distillation ritual (every cycle boundary)

Before the next dispatch:

1. **Always:** update `state.md` — 1–3 lines: what returned, what changed,
   what's next.
2. **If a return proposed a lesson or a correction happened:** `lessons.md`.
3. **If recognition or correction happened:** `people/<member>.md`, same
   moment, not later.
4. **If a retro or incident changed how the team works:** `agreement.md`,
   with the scar comment.

Later comes after compaction. A heavy ritual gets faked; a three-line habit
doesn't. At milestones, also replace stale status, resolve or reassign open
items, merge duplicates, and prune the progress log. When a stored claim
conflicts with new evidence, compare artifact identity and conditions before
deciding which is stale; write the supported conclusion with its evidence,
and tell affected owners rather than leaving the correction in an appendix.

## Resume reconciliation

After a session break or compaction:

1. Read `state.md`, then the repo: `git log` since the recorded commit.
2. List the team on its channel (Herdr: `agent list`, your workspace only);
   compare session ids. A new session id in a known pane is a new mind — it
   gets a re-brief from the record, not an assumption of memory.
3. On any conflict between the record and the repo, reconcile by what kind
   of fact is in conflict, fix the losing side, and say what you fixed:
   - **What the human wanted** (requirements, approvals, intent): the
     record's authority entries and the human's messages win — no repo
     state grants authorization.
   - **What was actually done** (artifacts, commits, file state): the repo
     wins — rebuild the record's claims from the evidence.
   - **How work is coordinated** (ownership, task state, acceptance): the
     record's task ledger wins for ownership; check each acceptance claim
     against its evidence before trusting it.
   - **Produced but unaccepted**: preserve it as exactly that state — work
     that exists but was never accepted is neither done nor absent. Don't
     erase it, don't count it as progress, and don't redispatch over it
     blind.
   Re-dispatching completed work is the most expensive resume failure;
   inspect the actual state before assigning anything.
4. Keep every `Hold:` line. A hold lifts only on its `lifts when:`
   condition, which comes from the human's own words: a wait for the human's yes
   stays until that yes; an explicit conditional grant ("do it after 10:00")
   lifts once its condition is checked and met, with no second yes; a grant
   whose meaning is unclear stays held, and you ask once. New feedback alone
   grants no authority, though verified evidence may satisfy the human's
   explicit condition; unrelated feedback, a new session or a new attempt
   never lifts a hold or reopens a capped correction chain.
5. Label unverified historical claims; don't redo stable completed work just
   because the session was new.
6. Take the single first resume action.

## What the record is not

Not a transcript: store conclusions and rationale, not streams of
deliberation. Not feelings: agent development here means better context,
instructions, task fit, and tools — a file does not update weights or
establish enduring capability. Not cross-project intelligence. Keep secrets
and confidential business context out of it entirely. Local notes never
imply permission to publish, move records across projects, or write to an
agent's separate global memory; publication takes an explicit scope and
content review. This skill never publishes team records automatically.
