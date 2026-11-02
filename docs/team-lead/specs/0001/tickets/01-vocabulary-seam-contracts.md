# 01: Vocabulary seam — team record + brief/receipt/doorbell contracts

**What to build:** The agent-agnostic Markdown contracts every member and the lead share
(ADR-0002), as shapes plus validators, independent of any transport:

- **Doorbell vocabulary**: `DONE <task> <artifact>` / `HELP <task> <reason>` /
  `HELD <task> <waits-on>` / `STOPPED <task> <why>` — one line that works as a pane
  message a human can watch and as a durable record any agent can read.
- **Brief contract**: task files with stable ids and attempt ids (`7`, `7.2`), latitude,
  done-means, stop rule, return path — extending the team-lead skill's existing brief
  template rather than replacing it.
- **Receipt contract**: members close ids explicitly (`Closes: 7`); results land as
  sidecar artifacts; delivery is proven by receipts, never by transport return codes.
- **Team record shapes**: state, agreement (versioned), people, lessons, decisions —
  extending the existing team-memory reference; one writer per artifact.

**Blocked by:** 00 (Version the agency tree).

**Status:** done

- [x] Contract documents live in the team-lead skill tree, using GLOSSARY vocabulary
- [x] A validator accepts well-formed doorbell lines, briefs, and receipts, and rejects
      malformed ones with actionable errors
- [x] A doorbell line is demonstrated both as pane-visible text and as a parsed record
- [x] The existing team-memory/brief guidance in the skill references the new contracts
      without contradiction (no second vocabulary)
- [x] Good/bad sample fixtures exist for every contract shape

**Implementation note:** contracts shipped in 765a39c; review follow-up added
per-return validation (each `## Return` validates independently), a
`Closes:`-vs-frontmatter cross-check, frontmatter comment stripping and wider
key charset, one-line doorbell payloads, and UTF-8 decode errors as actionable
messages — selfcheck 31/31.
