# Record card

For work that keeps its state in a file: a team, or more than one session. A
solo request that fits one session keeps its checklist in the conversation and
needs none of this.

The checker reads the record; its refusals name the missing line and show the
form. The full rules are the reference, [phase-record.md](phase-record.md):
open the section a refusal names, not the whole file.

## The record

One note (`state.md` in the team folder, or the task note you already have)
with these three sections. Everything else in the note is yours.

```text
## Done means
- <claim>: <the check that decides it>

## Phase checklist
- [ ] Scope: <evidence>
- [ ] Grilling: <evidence>
- [ ] Implement: <evidence>
- [ ] Review: <evidence>
- [ ] Retro: <evidence>
- [ ] Report

## Workflow
Methodology: matt
Executor: <your name>
Route: build
Phase: scope
Next gate: <what must be true before the next phase>
Start: <full commit SHA, or sha256:<digest>>
DDD: n/a: <reason>
UX: n/a: <reason>
Grilling: interview: <the decisions still open>
Procedure: ~/.agents/skills/engineering-workflow/SKILL.md
Procedure: ~/.agents/skills/ask-matt/SKILL.md
Loaded: ~/.agents/skills/engineering-workflow/SKILL.md | <your name>: sha256:<digest> <how you read it> at:<UTC>
Loaded: ~/.agents/skills/ask-matt/SKILL.md | <your name>: sha256:<digest> <how you read it> at:<UTC>
```

Checklist items are the route's steps, in order, from the last section of
[workflow-map.md](workflow-map.md); the build route above is the short branch.
`Workflow` holds only `Key: value` lines and ends at the next `## ` heading.
A lead adds `Procedure` and `Loaded` lines for `team-lead`, and for each
specialist it loads itself.

## The gates

```sh
v=~/.agents/skills/team-lead/scripts/validate_contracts.py
python3 $v workflow <record> --gate entry      # before a dispatch or a build step
python3 $v brief <brief> --matt                # each brief, before it is sent
python3 $v receipt <brief> --matt              # each return, before it is accepted
python3 $v workflow <record> --gate review     # before a review; needs a Snapshot line
python3 $v workflow <record> --gate accept     # before the whole task is called done
python3 $v stamp <record> "start <step> | passed | <evidence>"
python3 $v read <SKILL.md>                     # prints a body and the digest for its Loaded line
```

Read each command's exit status itself; a pipe hides it.

## The order

1. Load a step's bodies, and write their `Loaded:` lines with the time.
2. Run the gate. On exit 0, `stamp` the step's start Check. A stamp records
   what you hand it, so stamp only what you saw pass.
3. Then do the step, or send its brief.

A worker does the same inside its brief: it reads the bodies the brief lists,
then checks the brief, and that check's time is its start Check. A read
stamped after its step's start Check is late and is refused.

## What each phase adds

| When | Add to `Workflow` |
|---|---|
| The path is chosen | `Route decision: multi-session: no; reason: <why> at:<UTC>`, or the `yes` form naming the spec and tickets |
| The human cuts a step | `Cut: <steps> | <the human's words> | <where they said it>` |
| The plan is grilled | `Grilling: accepted: sha256:<digest> | <plan>`; the plan has `## Accepted scope`, and `## Design decisions` with a `Griller:` line |
| You coordinate and others write | `Implement: n/a: coordination: <what workers own> at:<UTC>` |
| Before review | `Snapshot: <review JSON from review-snapshot.py>`, or `sha256:<digest> | <artifact>` for work outside Git |
| After a build or fix | `Retro: sha256:<digest> | <retrospective file>` and `Check: retro | passed | <evidence>` |
| Before acceptance | one `Check: <claim> | passed | <evidence>` per Done-means claim |

After a compaction, add a new `Loaded:` line beside the original for each body
you reload; the original stays.
