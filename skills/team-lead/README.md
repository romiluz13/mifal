# team-lead

The engineering-manager skill for agent teams: own the outcome, brief well, check real
evidence, coach, recognize, and run retros that change things. `SKILL.md` is the skill;
`references/` carries the deep guidance (communication, messages, team memory, herdr,
development); `agents/` carries model configs.

For Herdr transport selection, read `references/herdr.md`. Sustained guarded
socket coordination is agency tooling at `~/.agents/mifal/tools/herdr_adapter/LEAD.md`;
small peer exchanges can remain inline. Neither path makes idle a completion proof.

## Layout

- `SKILL.md` — the skill itself (moments M1–M10, hard lines)
- `GLOSSARY.md` — the fleet vocabulary (doorbell, transport seam, stewardship terms)
- `references/` — deep guidance the skill points into
- `references/contracts/` — the machine-checkable fleet contracts (doorbell, brief,
  receipt, team record) per ADR-0002
- `scripts/` — the contract validator (`validate_contracts.py`, stdlib-only) and its
  good/bad fixtures, plus `resolve_role.py` (merges role defaults with project
  overrides into a member's effective onboarding) and `check_compliance.py` (tiered
  AGENTS.md compliance: rule classification, per-task reports, the dispatch gate,
  record history)
- `roles/` — shipped default role folders (`researcher`, `implementer`, `reviewer`,
  `_generic` fallback): onboarding pointers, brief templates, doorbell instructions,
  tool expectations; projects override under `<project>/.team/roles/<role>/`
- `agents/` — model configs for the lead
- `docs/adr/` — accepted architecture decisions (socket transport, vocabulary seam)
- the numbered design specs, each with its `tickets/` tree, live in the Mifal repository at
  `docs/team-lead/specs/`, outside the installed skill
- `stewardship/` — the lead's registries: generated skill inventory (reconciled from the
  agency tree), curated overlays, member capability briefs, and the per-member tool
  ledger, plus `steward.py` (stdlib-only CLI: build / check / brief / ledger / who) and
  the shipped compliance tier defaults (`compliance-tiers.json`)
- `recruitment/` — the human-gated hiring flow: `recruit.py` (stdlib-only CLI: gaps /
  pitch / onboard / record) detects capability gaps against the fleet's briefs and tool
  ledger, pitches pool-skill specialists as durable pitch files, and onboards approved
  hires through `resolve_role.py` + `steward.py brief add`; it writes `pitches/`, `gaps.md`
  (append-only gap ledger) and `onboarded/` as it runs

## Version control

Skill content (everything under `skills/`) is versioned by the skills pool repository —
`skills/.git` — not by the agency repository at `~/.agents`. Stewardship edits to this
skill — spec, ticket, ADR, glossary, registry changes — are commits in the skills repo.
Agency-level config (scripts, lock file, invocation policy) commits in the `~/.agents`
repository. Never commit another author's in-flight changes alongside your own: stage
explicit paths.
