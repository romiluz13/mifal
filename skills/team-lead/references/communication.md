# Briefs, returns, and team channels

Read when onboarding teammates on a channel, writing a brief for ambiguous
or consequential work, dispatching review or research, running agents in
parallel, or recovering from a missing reply or a stop. The method doesn't
depend on any provider or transport. When the channel is Herdr, also read
[herdr](herdr.md).

## Discover before dispatch

Find the real channel: terminal panes, subagent tools, an inbox, or another
authorized surface. Confirm each target's identity, current activity,
workspace, and access. Work already in progress belongs to its owner;
coordinate a handoff before replacing it.

A friendly model name is a label unless the environment verifies it. Record
the difference. Don't switch a session's provider or create replacements
because a preferred model is missing. Ask for a missing connection, and keep
doing the work that doesn't need it.

Adapt to the transport:

- **Shared filesystem:** send a path plus the smallest instruction, and
  confirm the recipient can read it.
- **No shared storage:** send the excerpt or attachment with its identity and
  limits. Never send a path the recipient can't open.
- **No messaging:** say plainly what can't be delegated, then write a handoff
  ([Handoffs](#handoffs)) or work locally as authorized. Never invent replies.
<!-- scar: 2026-10-16 — management research #11: a handoff written with no shape is the unstructured handoff that loses the first resume action -->

## The brief

Give enough context for independent judgment, and no more. Small tasks get
small briefs. The checkable shape — identity frontmatter (task id, attempt
id, owner, latitude, return path) and the required sections — is fixed by the
[brief contract](contracts/brief.md); what follows is how to fill it well.

- **Why:** one sentence tying the task to the user's outcome. It's the
  tiebreaker for every call you didn't anticipate.
- **Outcome**, not procedure. Leave the approach open where judgment matters.
- **Kind:** research, implementation, review, or a bounded experiment, so a
  reviewer doesn't quietly become a second writer.
- **Latitude:** *Look* (investigate, change nothing) · *Propose* (recommend,
  the lead decides) · *Do & tell* (decide within these bounds, report) ·
  *Own* (end to end, report at milestones).
- **Pointers**, worded by reach condition: "read the deploy section of
  `ops.md` before planning" beats "see `ops.md`". The wording decides whether
  the worker reaches the material. Cite method instructions by reference.
- **Current state:** the artifact or revision to start from; ownership and
  allowed changes; dependencies and constraints; shared resource limits.
- **Workflow:** the selected methodology, current phase, required skill
  paths, scheduler and integration owner. A child inherits that selection;
  its harness's default cannot silently replace the parent's workflow.
  Select procedures for this task and phase, not the entire skill catalog.
  Confirm that the worker can load their actual bodies through its harness
  or the shared filesystem. Request the loaded paths and the relevant
  behavioral evidence in its return; metadata alone is not a load.
  For Matt engineering, use the entry's [phase record](../../engineering-workflow/references/phase-record.md)
  in the existing state. Put the selected phase and procedures in the brief,
  point to the parent checklist rather than copying it, and request
  `validate_contracts.py brief <brief> --matt` before work and
  `receipt <brief> --matt` on return. A brief that keeps its own Phase
  checklist uses its route's step names in order from
  [workflow-map.md](../../engineering-workflow/references/workflow-map.md)
  Required steps; otherwise it points to the parent checklist with `State:`.
  The lead runs the entry/review/accept checks at their boundaries. Native
  interpreter records retain authority; file checks are not universal tool
  interception.
- **Least sure of:** the assumption most likely wrong, and a request for the
  one observation that would settle it. This replaces "any concerns?", which
  gets silence or invented objections. It is the lead's own premortem; the
  worker's comes in its first reply (below).
- **Done means:** named claims, each with its check (below).
- **Stop rule:** after a bounded number of failed approaches or a time cap,
  stop and write up what was learned. Stopping honestly is a good outcome;
  reinterpreting the goal to look successful isn't.
- **Development target**, when this task can exercise it, with any earlier
  feedback that applies.
- **Subagents:** none, named, or the worker's call within an envelope (below).
- **Return:** the file to write and how to signal (on Herdr, the doorbell,
  per the [doorbell contract](contracts/doorbell.md)).
- **First reply:** before the work, the worker restates the goal in one
  sentence, asks at most one question that exposes a tradeoff, and gives one
  premortem line, "this fails if ...", naming the failure it would least
  like to find late. Authorized work proceeds while an answer is pending. The
  worker repeats the premortem as the first line of its return's Result, with
  what became of it, and the reviewer checks those failure modes. The role
  templates carry this line.
<!-- scar: 2026-10-16 — management research #1 and #9: a misread goal surfaces late; a restated goal and a premortem at dispatch are cheap -->

State the target behavior positively. A prohibition pulls the forbidden
behavior into the worker's context, so keep one only as a hard guardrail,
paired with the positive target.

## The griller's brief

A griller interviews the lead's plan before the plan counts as accepted
([phase checks](../../engineering-workflow/references/phase-record.md)). Its
brief carries the round format and the valid doorbells up front, so it never
guesses the protocol. `<pool>` is the absolute path of the shared skills pool.

```text
---
task: <n>
owner: <griller>
latitude: look
kind: review
return: <record root>/tasks/<n>.md
---
# Grill the lead's plan: <plan name>

## Why
<one sentence: what the plan settles for the human's outcome>

## Outcome
- Grill the lead on `<plan path>` with Matt's grilling procedure, in rounds, at most <cap> (normally 2-3).
- Write round <k> to `<record root>/tasks/<n>/round-<k>.md`: numbered questions, each with your recommended answer, worded so "yes" accepts it. Then ring `HELP <n> grilling round <k>: <record root>/tasks/<n>/round-<k>.md`.
- The lead answers in `<record root>/tasks/<n>/answers-<k>.md` and rings you back. Recompute the frontier from the answers and continue until it is empty.
- The files are authoritative and a ring only points at one. Never ring ROUND: it is not a doorbell type. Never type into, submit or clear another member's composer.
- Facts are your job: read the real files. Ask the lead only for decisions.
- On an empty frontier, run `validate_contracts.py design-digest <plan path>` and write your Return. Its Result carries three lines of their own: `Plan path: <plan path>`, `Design digest: sha256:<digest>` and `Frontier: empty`. Check the Return with `validate_contracts.py receipt <record root>/tasks/<n>.md --matt` until it exits 0, then ring `DONE <n> <record root>/tasks/<n>.md`.
- Plan-readiness is not the human's acceptance: scope and reserved choices stay with the human.

## Least sure of
<the design decision most likely wrong, and the observation that would settle it>

## Done means
- findings: the plan grilled to an empty frontier, with decisions settled, decisions escalated to the human and changes recommended
- binding: the Return names the plan and its design digest, says Frontier: empty once, and `receipt --matt` on it exits 0

## Reserved
<the agreement's Reserved text, unchanged>

## Workflow
Methodology: matt
Executor: <griller>
Route: plan
Phase: resolve
Next gate: frontier empty, then the plan carries a Griller line for this task
Start: sha256:<digest of the plan to grill>
Grilling: interview: <decisions under test>
DDD: n/a: <why no documentation-validation trigger applies>
UX: n/a: <why no user journey changes>
State: <record root>/state.md
Procedure: <pool>/engineering-workflow/SKILL.md
Procedure: <pool>/ask-matt/SKILL.md
Procedure: <pool>/grill-with-docs/SKILL.md
Procedure: <pool>/grilling/SKILL.md
Procedure: <pool>/domain-modeling/SKILL.md

## Stop rule
Stop after <cap> rounds, or when a round raises nothing new, and write up what is open.

## Return
Write the Return in this file (`Closes: <n>`), then ring `DONE <n> <record root>/tasks/<n>.md`.
```

The checker proves the structure, not that the rounds were a real interview:
the lead's reviewer reads them. The plan then names the griller's task as
`Griller: sha256:<digest> | <task file>`, and the gate holds that its owner is
not the lead.

## Acceptance evidence

Name the claims the worker must establish and the check for each. On return,
each claim gets a status: **passed**, **failed**, or **untested** with the
reason. A claim the return doesn't address is untested, never assumed.
Anchor each status to the revision, artifact identity, or digest it was
checked against, so a later change can't make old evidence look current.
For a defect fix, capture the failing state while reproducing, before the
fix, when it's cheapest.
For a consequential fix, someone other than the builder states the expected
outcome before the fix lands, and one Done-means claim names a negative
control: the original defect, or a deliberately weakened implementation,
fails the check and the fix passes it. A test whose expected value the
builder computed with the code under test is not independent. Prose that no
agent or gate follows needs none; prose that agents follow as policy, and
test oracles, are consequential ([review routing](review-routing.md)).
The reviewer executes the expected-outcome check, or names why it cannot; a
narrative of red and green is not the check.
<!-- scar: 2026-10-16 — Astra R6: a worker-written test run by the lead still needs an independent expected outcome and a negative control -->
<!-- scar: 2026-10-16 — Astra task 12 F3: two reviewers accepted a casefold fix that does not equate SPRİNG10 with SPRING10, from a narrative of red and green, without executing the comparator -->

Check specialist use when it matters to the result. If a worker skipped a
selected procedure, ask whether it was unavailable, inapplicable, or missed.
Accept an applicable alternative with evidence, or request the missing check;
reading a skill after the work does not prove its procedure was followed.
The selected methodology owns progression, the lead owns selection and
acceptance, and the worker owns applying the procedure within its brief.

## The return

One spec; the task file (`tasks/<id>.md` in the team record) holds it below
the brief. Its checkable shape — the explicit `Closes:` id, claim statuses,
sidecar artifacts — is the [receipt contract](contracts/receipt.md).
Delivery is proven by that structured receipt, never by a transport return
code. A native task tool or existing Pi journal may hold the same return:
declare its task/attempt identity and retrieval surface in the brief, retain
the claims and artifact identities below, and reuse the existing task state.
When writes are permitted, persist any session-only return needed for resume
in the existing record before compaction. For an explicitly read-only task,
keep the receipt in the conversation and report its persistence limit.

- **Result:** the finding or change, and the artifact identity (commit,
  path, digest).
- **Claims:** each with its status and the revision checked.
- **Evidence:** what was actually inspected or produced, as pointers.
- **Limits:** failed approaches, what's unknown, cleanup done or owed. "I am
  not sure" and an honest `untested` are good reports: name them when they
  help, and never penalize them.
<!-- scar: 2026-10-16 — management research #14: an agent that green-washes status is a team where nobody speaks up -->
- **Decision needed**, if any, with a recommendation.
- **What I wish the brief had said:** one line, or "nothing".
- **Lesson proposed:** optional; "When <trigger>, do <rule>". The lead checks
  it before it enters the shared record.

Write the receipt first, then show a short summary in the worker's own chat:
task/attempt, outcome, decisive checks, blockers and the evidence path. The
lead gives the human a summary of acceptance and remaining limits. These
summaries derive from the receipt; they do not become another task record.
Keep the separate signal compact: status, task id, and path. The declared
receipt surface is authoritative and the signal only a hint: deliver it
once. If the lead isn't ready, retry every 2 minutes for up to 30 minutes
rather than sending to a busy lead, then let the receipt stand alone. The
lead's own wait checks the declared receipt surface, not only the signal
channel.

A review can target uncommitted or non-Git work. Identify the snapshot with
an accessible copy or patch and its base, plus a digest when versions could
be confused. Committing only to get a review is optional.

**Research returns** add: the answer, primary sources with version and scope,
contradicting evidence, and what's still unknown. The lead synthesizes and
checks the decisive source rather than repeating the search.

## Review and disagreement

Give reviewers the requirement and the raw artifacts before your favored
explanation. The hard lines in SKILL.md apply: no suppressed findings, no
wrong finding accepted for a clean score, and a named cycle cap.

When reviewers disagree, compare their rationales and the decisive evidence.
A factual dispute is settled by checking the artifact. Reframe the question
for everyone only when the disagreement exposes competing readings of the
requirement. Averaging verdicts or siding by rank settles nothing.

A review score is a gate, not a verdict. Resolve each finding by fixing it
or rebutting it with stated grounds; user requirements and accepted project
decisions outrank a reviewer's preference. At the cap with findings open,
stop and report.

A rebuttal stands on a reproducible check, a cited source contract, or an
authoritative decision record that the reviewer can open
([receiving-code-review](../../receiving-code-review/SKILL.md)); prose
disagreement does not. A genuine judgment that none of these settles goes
to the lead, not to whoever argues harder.

**Review depth.** Every change gets a bounded independent review; risk sets
the depth and the owner, never approval or merge. Skill and workflow
Markdown, hooks, verifier and test oracles, CI, permissions, ownership
policy and dependency changes are consequential whatever their extension or
size. A rename inspects both paths. An unclear case goes up one level, with
the reason in the task record. The table and the router are in [review
routing](review-routing.md). **Routing is not approval:** it never approves
or merges, and it never lowers the independent-review requirement of an
authorized round.
<!-- scar: 2026-10-16 — Astra item 5: calling instruction or test changes docs-only or tests-only excludes their effect on the gate -->

## Subagents and recursion

For each assignment choose: the worker does it directly, uses named
subagents, or decides within an envelope. Children fit independent
questions, useful context isolation, or independent review. A small lookup or
a tightly coupled edit stays with its owner. Spawning is not progress.

The envelope names the allowed child roles, slots, the shared budget (time,
iterations, or tokens where measurable), and the stop or escalation
condition. Descendants count against the same team limits; delegation
doesn't reset the allowance. If cost can't be measured, say so and bound
calls, time, or rounds. Verify the harness's real capacity and your authority
before spawning; otherwise use an existing worker or a serial plan. Change
models only with authority.

A parent gives children the same project boundary, pointers, ownership, and
evidence contract, and checks their returns. Before yielding, it reports
active descendants and remaining work. At a limit, it returns partial
findings and the missing evidence instead of adding another layer.

## Parallel agents in one repository

Isolation is mechanical, not social. Each writer gets its own worktree and
branch from the selected workflow's recorded baseline. For Matt's
`implement-spec`, that is the integration branch, including accepted
prerequisites; workers merge the current integration tip before returning.
For independent changes outside that route, use the agreed base (normally
the default branch). Never build on the default branch, and never
reuse another agent's worktree, branch, or uncommitted work.

Record one scheduler for the dependency graph. Team Lead owns the briefs,
capacity and acceptance; `implement-spec` owns frontier and merge order.
Children coordinate further workers only within their explicit envelope.
An active Pi workflow keeps its existing interpreter, journal and one writer.

Before starting, enumerate every open pull request with pagination and check
its changed files. On GitHub:

```sh
gh api --paginate 'repos/{owner}/{repo}/pulls?state=open&per_page=100' --jq '.[].number'
gh pr diff <n> --name-only
```

If the task needs files another change is editing, stop and ask. If the
enumeration fails or was bounded, report incomplete coverage, not "no
overlap". Resolve lockfile conflicts by regenerating, never by hand-merging.

Worktrees don't isolate the machine. Confirm a dev-server port answers the
authorized agent's own process before trusting what it serves, and never run
schema experiments against a shared database. A green check served by
another agent's process is not this task's evidence.

The team record has one root, named by absolute path in `agreement.md`. Each
agent resolves record paths against that root, never against its own
worktree; a brief gives the absolute path when worktrees differ.

Name one integration owner for parallel work. Milestone acceptance runs on
the combined revision; branches that are each green alone don't prove the
merge is.

Routine exchanges need short messages, not a report, manifest, meeting, or
extra reviewer each time. The lead consolidates results and tells dependent
owners when a decision changes.

## Handoffs

A handoff file has four headings, in this order: **Situation** (what is
happening now and what is blocked), **Background** (what led here; what is on
disk and what is session-only), **Assessment** (what you believe is true and
how sure you are; "not sure" is a valid entry), **Recommendation** (the
single first resume action, who decides, and what would change it). Write for
a reader who can open the pointers and nothing else.
<!-- scar: 2026-10-16 — management research #11: free-text handoffs have the failure shape of unstructured human handoffs -->

## Delivery, interruption, and recovery

Sending, acknowledgment, completion, and acceptance are four different
events. Use the task id and observed state so an old completion isn't read
as the answer to a new assignment; a correction carries an attempt id
(`7.2`) and keeps its own return section.

On a timeout, inspect the target before resending; the first send may have
landed. Bound each wait by urgency and expected duration. Tell the human
about consequential changes, not routine polling.

When a worker becomes unavailable, preserve its evidence and inspect its
active work before reassigning. Stop or isolate the previous writer before
anyone else touches the same artifact. An unavailable service says nothing
about reasoning quality. After a restart, refresh the contact and session
mapping and re-brief from the record.

A stop or scope change must reach every affected worker. Check for active
mutations and owned temporary resources before assuming the team stopped. A
thank-you or reflection message isn't an instruction to resume old work; say
so when it could be read that way.

On a stop request: notify every active owner, prevent new assignments, and
preserve uncommitted work. Report each owner's observed status. A stop nobody
acknowledged is unconfirmed, not done. If the channel can't show delivery,
record that and make one bounded attempt to communicate the stop, rather than
resending old work. Preserve by default; discarding, committing, or
transferring follows existing authority. Don't hold a requested summary
indefinitely for unreachable workers, and don't make the human choose to
abandon work just to end the session.

## Writing for people

Briefs, coaching, reports, and closing summaries are read by people and
agents alike; write them like it. Plain words: use, not utilize; help, not
facilitate. Active voice, with the actor named. Cut filler: "in order to"
becomes "to", "due to the fact that" becomes "because". One hedge is enough.
Say the mechanism or the number, not the feeling. Keep sentences short and
vary their length. A sentence that could appear unchanged in any project's
message says nothing about this one; cut it. Have an opinion when the
evidence supports one; a neutral list of pros and cons usually dodges the
judgment. No decorative emoji. Straight quotes. Apply these rules to text you
write or change; leave prose you didn't touch alone.

## Other channels

Herdr has its own guide: [herdr](herdr.md). Any other transport has to supply
the same functions through its own documented tools: identity, dispatch,
observation, and handoff. A missing optional channel skill doesn't stop you
leading through another authorized channel.
