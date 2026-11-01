# The brief contract

A brief is a durable file — `tasks/<id>.md` in the team record — that any
member can read at its own pace and any later reader can audit. This contract
fixes the checkable shape (identity frontmatter and required sections). The
guidance for filling it well stays in
[communication](../communication.md#the-brief); this contract formalizes that
template, it does not replace it.

## Shape

Frontmatter (plain `key: value` scalars, no lists or nesting), then Markdown
sections:

```
---
task: 7
attempt: 7.2        # only on corrections
owner: kai
latitude: do-tell
kind: implementation
return: .team/tasks/7.md
---

# Task 7 — <short name>

## Why
## Outcome
## Done means
## Stop rule
## Return
```

### Frontmatter fields

| Field | Required | Rule |
|-------|----------|------|
| `task` | yes | Stable task id, a plain number (`7`). Assigned by the lead, recorded in `state.md` before the brief is sent. |
| `attempt` | corrections only | `<task>.<n>` (`7.2`); must extend the task id. A correction gets its own attempt id, so a late `DONE 7` can't close `7.2`. |
| `owner` | yes | The member who holds the task. One owner. |
| `latitude` | yes | One of `look`, `propose`, `do-tell`, `own` (the skill's latitude words, lowercased; `Do & tell` → `do-tell`). |
| `return` | yes | The file the member writes and the doorbell names. A single path token; record-internal paths resolve against the record root named in `agreement.md`. |
| `kind` | no | research, implementation, review, or bounded experiment. |

Projects may add fields (the agreement names them); unknown fields never
fail validation.

### Required sections

- `## Why` — one sentence tying the task to the user's outcome.
- `## Outcome` — what done looks like, not the procedure.
- `## Done means` — named claims, one `- <claim>: <check>` line each. Every
  claim must be checkable; the receipt answers each with passed, failed, or
  untested.
- `## Stop rule` — the bounded number of failed approaches or the cap, and
  the instruction to stop and write up what was learned.

Recommended, per the existing template: `## Kind` (or the `kind:` field),
`## Pointers` (worded by reach condition), `## Current state`,
`## Least sure of`, `## Development target`, `## Subagents`, `## Return`
(the return path and the exact doorbell line to ring).

Recommended: `## Source`, which quotes the human's request with who said it
and when, or points to where it is recorded, so the worker can read the words
behind the brief. A worker that finds the brief contradicting its source
rings `HELP` rather than picking one.

A brief may carry an optional `Permission:` line under `## Current state`:
the worker's approval, filesystem and network permissions as launched, the
same as or narrower than the lead's (on Herdr, the
[dispatch rule](../herdr.md#dispatch)). It sits there because the
`## Workflow` check refuses fields it does not know. The reviewer checks the
line; the validator does not rank permission modes, which differ across agent
kinds.

## Rules

- **The brief is a file, not a message.** Pane prompts point at the file;
  long context never depends on scrollback.
- **Ids are stable.** The task id never changes; corrections add attempt ids.
  The same id appears in the brief, the doorbell, and the receipt.
- **Small tasks get small briefs** — the required fields and sections are the
  floor, not a quota.

Fixture: a well-formed brief is `scripts/fixtures/brief/good/task-7.md`;
check any brief with `validate_contracts.py brief <path>`.
