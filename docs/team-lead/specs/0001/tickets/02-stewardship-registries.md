# 02: Stewardship registries — skill inventory + tool ledger + capability briefs

**What to build:** The lead's stewardship picture of what the fleet can do:

- **Skill inventory**: lead-curated registry of skills (what exists, maturity, owner)
  merged with member **self-reported capability briefs**.
- **Tool ledger**: per-member MCPs and connectors, kept current by the lead.

The inventory builds on the agency's existing configuration infrastructure (the skills
catalog, scopes, invocation policy, lock file) — it reads and reconciles with them, never
duplicates them into a second source of truth.

**Blocked by:** 00 (Version the agency tree).

**Status:** done

- [x] Inventory generated from the real agency tree reflects actual installed skills,
      reconciled with the existing catalog/config
- [x] A member's self-reported capability brief merges into the inventory without
      clobbering the curated view (sources stay distinguishable)
- [x] Tool ledger records a real member's MCPs/connectors, with staleness visible
- [x] An assignment query ("who has demonstrated fit for X?") answers from both curated
      and self-reported sources
- [x] Registry changes are commits (stewardship edits leave history)

Implemented in `team-lead/stewardship/` (`steward.py` + overlays + briefs +
tool-ledger.json + committed generated output).
