# Active phase record and checks

Read at Matt entry, resume, assignment and acceptance. Keep this information
in the existing task note or native task state. This is a checkable surface
for the engineering contract, not another workflow or tracker.

## Prepare the active record

Create `## Phase checklist` with ordered checkbox items from the selected
route in Engineering Workflow. Each item names its completion evidence;
mark it complete only after checking that evidence. Any line there
that looks like a list item (`*`, `+`, a number, or a `-` with no space) must be exactly
`- [ ] <item>` or `- [x] <item>`; malformed or blocked markers hold the check
instead of disappearing from it. Prose lines stay legal. Maintain the active
state separately from historical summaries so superseded statements cannot
govern a return. A worker uses `State: <parent task-state path>` and records
only its assigned phase. A solo task needs neither a team folder nor Herdr.

Put one `## Workflow` section in the active note or before the brief's
return. Use plain `Key: value` lines; a leading `- ` is also accepted.
Resolve placeholders before checking. Example shape:

This section is reserved for the fields shown below, repeated `Procedure`,
`Loaded` and `Check`, their documented aliases, and optional `Snapshot`,
`Scheduler`, `Integration owner`, `Implement`, `Grilling`, `Route decision`, `Cut` and `Retro`. Unknown colon-delimited keys are refused
to catch typos; put explanatory prose outside this section.

```text
## Workflow
Methodology: matt
Executor: <accountable agent name>
Route: build
Phase: plan
Next gate: <observable condition before implementation>
Start: <full starting commit SHA or sha256:digest>
DDD: n/a: <why no documentation-validation trigger applies>
UX: applies: <affected journey or interaction>
Procedure: ~/.agents/skills/engineering-workflow/SKILL.md
Procedure: ~/.agents/skills/ask-matt/SKILL.md
Procedure: <selected planning procedure path>
Procedure: ~/.agents/skills/team-lead/references/ux-acceptance.md
Loaded: ~/.agents/skills/engineering-workflow/SKILL.md | <executor>: sha256:<body digest> <complete-read pointer>
Loaded: ~/.agents/skills/ask-matt/SKILL.md | <executor>: sha256:<body digest> <complete-read tool/event pointer>
Loaded: <selected planning procedure path> | <executor>: sha256:<body digest> <complete-read pointer>
Loaded: ~/.agents/skills/team-lead/references/ux-acceptance.md | <executor>: sha256:<body digest> <complete-read pointer>
State: <parent task-state path, only when the checklist is elsewhere>
```

`Route` is research, plan, build, debug or review. Begin `Phase` with the
local route's phase word, for example `plan`, `implement`, `review`, `verify`
or `report`; research uses `investigate` and `synthesize`, debug uses
`reproduce`, `hypothesis`, `diagnose` or `fix`. The checker lists legal words
on refusal. Add detail after the word, such as `implement slice 2`.
`Phase` and `Next gate` describe current work, not permission to advance;
writing a legal word cannot establish that the agent actually stayed in it. Methodology owner
Matt is distinct from `Executor`, which matches the brief's `owner`.

`Start` is a full 40-character commit SHA or `sha256:<64-character digest>`.
Research/plan work that has no code baseline can use `none: <reason>`.
Moving labels such as HEAD or main do not pin work. The checker validates
the identity's form; the agent must compare it with the actual starting
code/artifact and reconcile uncommitted work before acting.

DDD and UX each require `applies: <trigger>` or `n/a: <reason>`. Unresolved
applicability holds the gate. When applicable, list and load the relevant
DDD procedure or UX acceptance reference in the selected phase. Research
and planning define affected checks without authorizing a build. Motion is
selected only when affected, through the existing interface branch.

## Select procedures for this phase

For build work, record `Grilling: interview: <unsettled decisions>` while planning,
and select/load Matt's grilling wrapper and dependencies in the planning phase.
Before implementation, replace it with
`Grilling: accepted: sha256:<digest> | <existing plan/ticket artifact>`.
The evidence contains one nonempty `## Accepted scope` with
`Accepted: <actual user approval or accepted-ticket id> | <source pointer>`, and one nonempty
`## Design decisions`. Both a completed interview and a pre-agreed ticket use
this evidence; calling work concrete does not establish acceptance. Keep it in
the existing plan, not a new tracker. The checker verifies the current bytes
and required sections; the lead verifies the approval, decisions and task fit.
The same evidence is required when a debug task starts a fix. A worker inherits
the parent's evidence rather than conducting another interview. Matt adapter
task JSON forwards the optional `workflow.grilling` value into the brief.

Accepted means grilled by someone else. The human's quote covers scope only:
it sits in `## Accepted scope` with a source pointer (a file, a session log
path or a message location), and an `Accepted:` line inside any
`## Design decisions` or `## Design decisions <suffix>` section, written plainly
or as a list item, is refused. The design decisions rest on a griller:
`## Design decisions` carries at least one
`Griller: sha256:<digest> | <griller task file>` line (a relative path resolves
from the evidence artifact). The named task must hold up on every point:

- the file still hashes to the pinned digest;
- its latest return passes `receipt --matt`, and none of the claims in that
  return is `failed` or `untested`;
- its `owner` differs from this record's Executor and, when the record has a
  `State:`, from the Executor recorded there (compared without case). A
  `State:` file whose `## Workflow` section has no readable `Executor:` line
  (a bold field, a variant heading, the owner only in frontmatter, an
  unreadable file) is refused with "cannot determine the parent's Executor",
  whoever owns the griller. A record with no `State:` checks its own Executor;
- its Workflow lists the canonical `grilling/SKILL.md` as a `Procedure`, and
  its latest return records the complete read;
- its latest return says `Frontier: empty` exactly once. Code fences and HTML
  comments (an unclosed one runs to the end) hide a line from this check. Any
  other value, such as `Frontier: 2 open (Q3, Q4)`, is a nonempty frontier;
- its latest return names the plan it grilled and the design decisions it
  grilled, as two lines outside code fences and HTML comments:
  `Plan path: <the plan>` (a relative path resolves from the griller task, and
  the file must be the very file the record pins) and
  `Design digest: sha256:<digest>`.

The design digest binds the griller to the design decisions. It is the sha256
of every `## Design decisions*` section of the plan, heading and lines, with
each `Griller:` line removed (the plan's own `Griller:` lines sit inside the
section, so a hash of the whole plan would be circular). Line endings, trailing
whitespace and a section's closing blank lines do not count; every other
character does, fenced text included. Print it with
`validate_contracts.py design-digest <plan>`, which prints `sha256:<digest>`
(exit 1 when the plan has no design section or leaves a comment or fence open
inside one). The gate recomputes it and refuses
a mismatch with "the griller did not grill these design decisions". Editing the
design after the griller closed, or naming a griller of another plan, therefore
needs a new griller return; editing `## Accepted scope` does not. A worked
example: the section `## Design decisions`, `Use the existing interface.`, an
empty line and `Second line.` hashes the bytes
`## Design decisions\nUse the existing interface.\n\nSecond line.\n`.

Fences and HTML comments are read by one scanner, as CommonMark reads them: a
comment and a fence never nest. Inside a comment only `-->` counts (so a
backtick line inside a comment opens no fence, and `<!-->` is a whole comment);
inside a fence only its closing fence counts (so a literal `<!--` there opens no
comment); otherwise openings are detected. A backtick line with a backtick in its
info string is a code span, not a fence, and a `<!--` in a code span opens no
comment. A comment or fence left open inside a `## Design decisions*` section, or
anywhere in a griller's latest return, is refused with "unclosed comment or
fence in <file>; the gate cannot tell what is visible", because the gate cannot
tell what a reader sees.

One passing griller is enough; when none passes, the refusal lists why each
failed. The checker proves this structure, not that the named task was a real
interview of the lead: the lead's reviewer reads the griller's rounds. A griller
brief therefore tells the griller to list and load `grilling`, to write
`Plan path:`, `Design digest:` and `Frontier: empty` in its latest return's
Result, and to pass its own claims.

Cutover. The rule applies at the `brief --matt` and `workflow --gate` checks
(entry, review and accept), which run before a dispatch, a review or an
acceptance. `receipt --matt` on an already closed return is not re-gated by it:
that brief passed the check at dispatch, and a closed receipt is never rewritten
or re-gated (inspect old receipts as historical). There is no version, legacy
or opt-out key: an unknown Workflow key is refused, and evidence that calls
itself legacy still needs a griller. An open record, and old evidence reused to
justify a new transition, meet the rule at their next gate: reconcile them with
a real griller task or the human's recorded grant for scope, never with
invented rounds. A passing worker receipt does not make a parent's
`--gate accept` pass.

The plan route needs grilling too. A plan record at `resolve` or later
(`resolve`, `plan`, `review`, `verify`, `deliver`, `report`) carries a
`Grilling` line: `interview: <unsettled decisions>` while the interview runs,
`accepted: sha256:<digest> | <artifact>` when it is done. An unfinished
interview is refused from `review` on, delivery included. The phases before
`resolve` need none. The cutover above holds here: `receipt --matt` on a
closed plan return is not asked for a Grilling line it never had.

Record Ask Matt's multi-session branch in one `Route decision` line, before
acting on it:

```text
Route decision: multi-session: yes; spec: <path>; tickets: <path> at:<UTC>
Route decision: multi-session: no; reason: <why this work needs no spec and tickets> at:<UTC>
```

Stamp the line with the time you record it: a record with stamped start Checks
refuses an unstamped branch, and one stamped after its earliest `implement` start
Check (see below).

`yes` names both outputs, once each, before they exist. Pin each when it is
made, as `sha256:<digest> | <path>`; one digest covers one file, so name the
tickets index or artifact, not a folder. `no` states a reason, and neither a
placeholder nor punctuation alone is one: it needs a letter or digit. The gate
checks only what the proposed next action needs, read from `Phase` and the
selected `Procedure` bodies, so a producer is legal while its own output is
still unpinned:

| Next action | Ready first |
|---|---|
| spec producer (`to-spec` selected) | Grilling accepted |
| ticket producer (`to-tickets` selected) | Grilling accepted, spec pinned |
| build `implement` onward, or a review or accept gate on a build | spec and tickets pinned |

A pinned output must be readable, nonempty and unchanged since the pin. A
record that selects both producers is held to the ticket producer's needs:
give each producer its own phase. A plan under review is not held for the spec
it leads to. A selected producer is held to its needs whatever the `Route
decision` says, and when none is recorded: the branch is no way round the
interview. With `no` or no line, `to-tickets` has no spec to pin and is
refused until a `yes` line pins one. A plan record selects a producer only at
`resolve` or later; at `scope`, `inspect`, `context` or `research` it is
refused, because a spec or ticket producer runs after resolve. A build record
keeps the build phases and is not a plan record. The check validates a branch
that is recorded; it does not require one, though a selected producer is
checked either way. It applies at `brief --matt` and `workflow --gate`, and a
closed `receipt --matt` is not re-gated by either rule.

Ask Matt owns semantic branches. The checker enforces the execution
contract's mandatory minima, not a second copy of Matt's route graph:

- Behavioral build `implement`, `implementation` or `remediate`: select
  both canonical `implement` and `tdd` bodies.
- Code review or final build/debug acceptance: select `code-review`.
- Debug reproduction, hypothesis, diagnosis or fix: select `diagnosing-bugs`.
- Debug fix: also select `tdd`; the `Implement: n/a:` exemptions lift it as they do on build.
- Build/fix retrospective phase and whole-mission acceptance: select `retro`
  and `writing-for-agents`, and record their actual complete reads.
- DDD applies: select `ddd` and the current DDD phase body: `ddd-scope` for
  context/research, `ddd-ground` for planning, `ddd-verify` for review,
  verification and final reporting. An unrelated DDD body cannot substitute.

For a build phase containing only documentation changes, record
`Implement: n/a: docs-only: <concrete reason>`. A coordinating lead can use
`Implement: n/a: coordination: <what workers own>` and must select/load
Team Lead. This exception concerns implement/TDD, not review, DDD, UX or
acceptance. Compare the actual diff and worker assignments with the reason;
an agent's exemption declaration is not proof that the work qualifies.
The executing worker still selects and loads its own required procedures.
Herdr adapter Matt task JSON forwards the optional `implement` value into
the brief; tasks under another methodology keep their own contract.

List only the selected phase's procedures/references, one `Procedure` per
path, including the current Engineering Workflow and Ask Matt. `Procedures` and the adapter's `Required skill
paths` are accepted aliases for comma-separated paths. Each selected path
must exist and have a matching `Loaded: <path> | <executor>: sha256:<body digest> <read pointer>` record.
Core and applicable DDD/UX paths must resolve to the canonical bodies in
`~/.agents/skills`; symlink aliases resolving to those bodies are accepted.
A local stub with the same filename or directory name is insufficient.
Use a tool event, session-log location or declared return that identifies
the actual complete read. Metadata, partial reads and a late read do not
establish earlier compliance. Record the SHA-256 of the body that was read (for example, `shasum -a 256`
on that file). The checker compares it with the current body and holds a
changed version for reload. This detects stale recorded source identity;
it does not retrieve a trace or certify comprehension, timing or application.
Explicit read pointers beginning `partial`, `truncated`, `excerpt`, `snippet`,
`metadata-only`, `description-only` or `frontmatter-only`, or declaring
`coverage: partial`/`coverage: truncated`, fail the read check. Silent partial
reads are not detected by this declaration check.
Computing a current hash alone cannot turn an old/partial read into a new
complete read. When the source changes, read the changed body first.

For a filesystem retrieval, this optional command prints one complete UTF-8
body and a footer hashing the exact buffer printed:

```sh
python3 ~/.agents/skills/team-lead/scripts/validate_contracts.py read ~/.agents/skills/implement/SKILL.md
```

Keep one body per call and allocate enough output for the whole body.
If the tool reports truncation, read the missing content before work;
preserve the combined full-read trace. Record the real tool/event pointer.
The footer supplies `sha256:<digest>` and optional `bytes:<n>` for a line
like `Loaded: <path> | <executor>: sha256:<digest> bytes:<n> <read pointer>`.
When supplied, bytes must match the complete current body; the validator
uses the existing bounded reader during resume. Old digest/pointer records
remain supported. The command proves retrieval and printing, not exposure
through a truncating harness, comprehension, timing or procedure application.

The executor loads its assigned procedure. The coordinating lead loads its
router and selection/acceptance references, checks decisive worker evidence,
and does not read every technical reference merely to duplicate the worker.

## Only the human cuts; reads come before the work

`workflow-map.md` ends with a `## Required steps` section: one line per route,
and for build one per Ask Matt branch (`- build, multi-session yes: scope,
grilling, to-spec, ...`). The Phase checklist is the record of the phase
sequence. A step shows as done when a checked item's label, or its words
before the first colon, are the step's name (`- [x] To-spec: ...`; case,
punctuation and a leading "to" do not matter). `- [x] To-spec skipped` and
`- [x] Review later` are not the steps `to-spec` and `review`. Only the record's
own checklist is held to its own route; a parent `State:` checklist is held at
the parent's gates against the parent's route, and a worker with no checklist of
its own gets no step check. The branch is the record's `Route decision` (read
from `State:` when the record has none), so record it before the work that
depends on it. A build past the steps where its branches differ, with no
`Route decision`, is refused. A worker's `Route decision` that differs from the
parent State's is refused. When the record carries stamped start Checks (see
below), its `Route decision` carries an `at:<UTC time>` no later than the
earliest start Check of `implement`: an unstamped or later-stamped branch is
refused, because the branch must be recorded before execution began.

A step is **due**, and refused when not done, when a later step is already
done, at the `review` gate (every step before `review`), and at the `accept`
gate or in the `report` or `deliver` phase (every step). A step still ahead of
the record is pending, never a skip. A step that is listed but unchecked while
a later one is done is a skip, and the message says it is listed but not done.

Only the human cuts a step. Record it as

```text
Cut: <steps> | <the human's own words> | <where they said it>
```

`<steps>` are step names from the map, comma separated; the line may repeat. A
cut without a quote and a source pointer, with a placeholder in either, or
naming a step the map does not require for the record's own route and branch
is refused, and so is a cut with no `|` parts. When the source is a path (with
an optional `#anchor`), the file must exist and contain the quote. A cut also
lifts the independent minimum behind its step: `grilling` (or `resolve` on the
plan route) the Grilling line, `implement` the implement
and tdd bodies, `review` the code-review body on build and debug, `retro`
the retrospective at accept, and `to-spec` or `to-tickets` the pinned output
that `Route decision: multi-session: yes` holds implementation for. A cut in
the parent `State:` covers the worker. `receipt --matt` honours the same cut,
read with the same checks from the brief (above its Return) or the parent
`State:`, and waives the same minima for the worker (Grilling, implement and
tdd, code-review): a worker dispatched under a cut can be accepted, a cut inside
its own Return counts for nothing, and a cut that lifts nothing for the worker
changes nothing. A relative source resolves from the folder of the file that
holds the Cut line: the parent State for a cut it holds, the brief for the
brief's own. A path source larger than 2 MiB (2097152 bytes) is refused the same
way at every check; cite the part the human wrote in a smaller file. The check
proves the line has a quote and
a source, not that the human said it: the lead's reviewer reads the source. A
branch is not a cut: Ask Matt's branches shorten the path by its own rules, and
the opening "full workflow or cut?" question, asked with the recommended
answer (full workflow), shows the human what a branch drops.

Reads carry their time. Write a `Loaded:` line's read pointer with
`at:<UTC time>` (`at:2026-10-17T10:00:00Z`; seconds optional), and log the gate
run that opens a step as `Check: start <step> | passed | <evidence> at:<UTC time>`,
a new one as each step begins: `Check: start to-spec` when the lead runs
to-spec itself after the griller closes. `<step>` is a name from the workflow map's Required steps
(scope, grilling, to-spec, to-tickets, implement, review, retro, and each
route's own), or the route's phase word where the route has no such step; an
unknown name such as `start entry` is refused, because it would leave every read
unheld.

A body is on time when at least one `Loaded:` line for it is stamped no later
than the earliest start Check of the step its row governs. A later reload never
makes an earlier on-time read late; a late read is refused only when no read of
that body is on time, and it stays refused after the record's `Phase` moves on.
The steps: grilling, grill-with-docs and domain-modeling govern `grilling`;
to-spec governs `to-spec`; to-tickets governs `to-tickets`; implement and tdd
govern `implement`; code-review governs `review`; retro governs `retro`.
`ask-matt`, `engineering-workflow` and `team-lead` are held to the earliest start
Check of any step. Any other body is held to the phase word its row in
`workflow-map.md` names, and a body whose row names none to the record's `Phase`.
To reload a body (after a compaction, a resume or a changed hash), add a new
`Loaded:` line beside the original; the original stays, and a body whose only
read is late stays refused. The stamp is read whatever its case, and a space after the
colon is allowed; a form that starts with a digit but is not an ISO-8601 UTC
time is refused. A worker's own receipt is held the same way, its start Check
read from the brief or from its return. An unstamped line, or a step with no
stamped start Check, is not refused: it stays unverified, and the check prints a
`note:` saying how many lines. This is self-recorded order evidence, not authentication; whoever
writes the record writes its times. A closed `receipt --matt` is not re-gated by
the step or cut rules, as for every rule here; the read-order rule only bites
when a line carries a stamp.

## Hold the gates to Ask Matt's body

`workflow-map.md` (beside this file) lists every shipped skill with its route
and phase, invoker, invocation path, dependencies and evidence, and records the
Ask Matt body hash it was reviewed against. Every Matt check (`brief --matt`,
`receipt --matt`, `workflow`) reads it. The gate holds, with a message naming
the map, when the installed Ask Matt body differs from that hash, the map is
missing or malformed (including a repeated authoritative section or an extra
table, read as GitHub-flavored Markdown reads headings and delimiter rows;
raw HTML and blockquote or list nesting are not recognised), a shipped skill has no row, a row is not shipped, or a row places a
skill Ask Matt does not place. That check covers structure, coverage, category
and body freshness; whether a row's prose is right stays a reviewer's call, and
no gate proves it. To clear a changed body, review the
map against it, then update its `Ask Matt body:` line with the digest that
`validate_contracts.py read` prints. The map restates and attaches; it never
decides a branch.

## Reach the checks before proceeding

Use the shared, stdlib-only validator:

```sh
python3 ~/.agents/skills/team-lead/scripts/validate_contracts.py workflow <existing-state.md> --gate entry
python3 ~/.agents/skills/team-lead/scripts/validate_contracts.py brief <brief.md> --matt
python3 ~/.agents/skills/team-lead/scripts/validate_contracts.py receipt <brief.md> --matt
python3 ~/.agents/skills/team-lead/scripts/validate_contracts.py workflow <existing-state.md> --gate review
python3 ~/.agents/skills/team-lead/scripts/validate_contracts.py workflow <existing-state.md> --gate accept
```

The lead runs entry before build/dispatch. Workers run their brief check
before work, so a missing field can be challenged independently. The brief
check validates preparation and selected paths; the lead does not invent
the future worker's reads. Workers load before work and put their `Loaded`
lines in their own current return's Evidence section. The Matt receipt
check uses that latest return, not the parent's reads or an old attempt.
`receipt --matt` takes the complete brief with its return(s); a standalone
return without the governing brief cannot supply this preparation check.
The worker can use its existing task/journal to preserve a read at entry;
no second tracker is needed. Reconcile
the same active record after compaction; reload the engineering entry,
Ask Matt and current specialist, record the reads, and resume the first
incomplete phase. Preserve passed evidence only while its inputs hold.

Before review dispatch, add `Snapshot: <absolute review JSON path>` from
`~/.agents/mifal/tools/review-snapshot.py --repo <repo> --base <fixed point>`
with explicit owned `--path` scope, including owned untracked files.
The review/accept check calls that tool's `--check`; changed working/index
content holds the gate. This verifies identity, not review quality or scope
completeness. A fixed committed comparison still needs recorded scope and
evidence; the snapshot tool can record its identity without making a commit.

For non-Git work, use `Snapshot: sha256:<digest> | <actual reviewed artifact path>`.
The checker hashes that artifact's current bytes. It does not follow a
manifest's pointers; verify all named live artifacts separately when a
manifest describes multi-file work. Do not substitute a static manifest's
digest for the identity of changing code. On build and debug routes, the
checker refuses a pinned artifact whose name ends `.diff` or `.patch`, without
opening it: a frozen diff does not identify live code. This is a filename
heuristic; a renamed copy still passes, so reviewers decide whether the pinned
file is the deliverable. It also refuses a JSON snapshot whose `reviewable` is
`false` (its `--path` scope holds no changed file). Review, plan and research
routes and a diagnosis-only debug record keep both forms.

## Close the outcome, not a worker return

After build/fix verification, apply Matt's `retro` to the actual session/logs.
Enter the retrospective phase after loading `retro` and `writing-for-agents`;
the completed report is required at whole-task acceptance, not before starting it.
Record `Retro: sha256:<digest> | <retrospective artifact>` and
`Check: retro | passed | <session review evidence>` in the existing Workflow.
The artifact contains nonempty `## Sources` and `## Findings`; zero findings
are valid when explained. Acceptance checks its current bytes and the selected
procedure reads. These declarations do not certify retrospective quality.
One parent retrospective closes a coordinated build; bounded worker receipts
still validate their assigned phase without claiming parent completion.
Debug work that delivered diagnosis only can record
`Retro: n/a: diagnosis-only: <why no fix was made>`; a build cannot use that
exception. The lead compares the exception with actual changes. Proposals
do not authorize new environment edits; affected edits reenter review/verification.

Before execution, put the original required outcomes in the same authoritative
state's single active `## Done means`, one unique `- <claim>: <decisive check>` per outcome.
Any other list form in that section (`*`, `+`, numbered, or `-claim:` with no space)
is refused; prose lines stay legal.
Compare that list with the original request, accepted plan and open findings;
the checker cannot discover omitted requirements or certify the comparison.
Record blockers honestly. Scope changes need the actual user/project authority;
a blocked requirement cannot become an optional limitation to obtain a pass.

At whole-mission `workflow --gate accept`, nonempty named outcomes are
mandatory, including those in a referenced `State`. Every declared required
claim needs a matching passed Check. Duplicate requirement sections or
duplicate names on either the parent or local surface hold acceptance. Every Phase checklist execution item
must be checked. Only the final checklist item, exactly `- [ ] Report`
with no description, may remain open so acceptance occurs before delivery;
mark it after reporting and put what to report in `Next gate`. The older
`- [ ] Report: <text>` form is refused; migrate it by changing the line to
`- [ ] Report` and moving `<text>` to `Next gate`. `Verify/report` is
execution work and cannot use that exception.
Keep optional opportunities and historical checklists outside the active
required checklist. A failed gate holds completion; partial/blocked reporting
remains allowed and must describe the remaining work.

A worker's `receipt --matt` checks the assigned brief and its latest own
reads. It may pass while the parent's checklist remains open: that is a
worker return, not whole-mission acceptance. The lead still owns the final
phase and requirement reconciliation. Adapter `complete` means its registered
required tasks passed; it does not certify unregistered product scope or
replace the authoritative final workflow check.

Before accepting the active work, add one line per required claim:
`Check: <claim> | passed | <evidence at the final identity>`.
Missing claims or failed/untested/pending required checks hold acceptance.
Optional limitations belong in the existing limits, not a fabricated pass.
The lead compares these claims with the brief/requirements and checks their
meaning; the checker cannot discover requirements absent from the record.
Receipt checks test preparation, executor-specific read declarations and
structure; they do not themselves accept work or prove pre-work timing.

## Native authority and coverage

General brief/receipt validation stays unchanged. Use the explicit Matt
mode for Matt engineering; it refuses another methodology rather than
changing the selected owner. Another methodology keeps its own lifecycle.

An active Pi interpreter owns transitions and its journal. Bind this
information to its existing record and native gates; do not manufacture
another file/tracker just to run the Markdown checker. For a native/session
task tool, use its existing export or authorized persistence when available;
otherwise keep the short checklist there and report file validation unrun.

No universal hook or native-tool interception is installed. A caller that
does not run the check can bypass it. Herdr adapter tasks explicitly selecting
Matt now use these existing preparation and worker-receipt checks at init,
dispatch and acceptance, including bounded resume inspection. Generic tasks
retain their earlier contract. The parent still owns phase advancement, pinned
review snapshots and final acceptance checks; receipt shape and read records
do not prove all behavior occurred. Report configured,
recorded, observed and untested separately. A passing checker cannot turn
an unsupported skill-use claim into verified execution.
