# The team record contract

The team record is the fleet's shared brain: Markdown files in the project's
team folder, git-versioned, written so a returning lead can make a sound next
decision without reading a conversation. This contract fixes which artifacts
exist and who may write each. The working guidance — what goes in them, when,
and how to keep them honest — stays in
[team-memory](../team-memory.md); these are roles for information, not a
mandatory schema, and they are checked by review, not by the validator.

## The shapes

| Artifact | Holds | Writer |
|----------|-------|--------|
| `state.md` | `## Waiting on you` first, then mission with a pass/fail finish condition, authority boundary, roster (member, pane, agent kind, session id, role), active work (owner, latitude, expected time, return path), progress log, first resume action | Lead |
| `agreement.md` | How this team works: channel, doorbell format, latitude words, brief additions, definition of done, reserved vs authorized with the Consult matrix, record root. **Versioned** (v1, v2, …); retros diff it; scars noted as comments | Lead (authority boundary changes only with the human) |
| `people/<member>.md` | Capacity ledger: strengths, tool ledger, one development target, recognition with evidence | Lead |
| `lessons.md` | "When <trigger>, do <rule>" plus the incident it came from | Lead (members propose via receipts) |
| `decisions.md` | Decision · why · evidence · who challenged it · what would reopen it | Lead |
| `tasks/<id>.md` | The [brief](brief.md) plus the member's [receipt](receipt.md); sidecars in `tasks/<id>/` | Lead writes the brief; the owning member appends the return |

## Rules

- **One writer per artifact.** The lead owns every shared file; the only
  exception is the return section of a task file, which its owning member
  appends. Parallel writers need isolated worktrees.
- **Versioned, never silent.** The record lives in a git tree; agreement
  bumps carry a version number, and a change that came from a failure carries
  a one-line scar comment saying what happened.
- **One project, one record.** No cross-project profiles; the record root is
  an absolute path named in `agreement.md`.
- **Roles, not schemas.** A project that already keeps records keeps its
  folder; these shapes describe what each artifact is *for*. The machine-
  checked shapes are the [doorbell](doorbell.md), [brief](brief.md), and
  [receipt](receipt.md) only.

Worked examples (good and bad) live in `scripts/fixtures/record/`.
