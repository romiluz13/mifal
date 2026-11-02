# 07: Tiered AGENTS.md compliance

**What to build:** The lead checks AGENTS.md compliance in tiers, matched to what each
rule actually protects: Tier 0 (safety hard lines) enforced — a violation blocks
dispatch; Tier 1 (project conventions) checked per task and reported; Tier 2 (style
preferences) advised, never blocking. Tiers are configured per project (defaults
shipped, overrides allowed), and every compliance result lands in the team record.

**Blocked by:** 01 (Vocabulary seam — contracts).

**Status:** done

- [x] A Tier-0 violation blocks dispatch with the reason named (demo: a member in
      violation cannot receive a brief until resolved)
- [x] A Tier-1 issue appears in the task's compliance report
- [x] A Tier-2 item appears as advice only and never blocks anything
- [x] Tier assignment is configurable per project, shipped defaults sensible
- [x] Compliance history is queryable from the team record (a repeated violation is
      visible as repeated)

Implemented in `team-lead/scripts/check_compliance.py` (rule classification +
detectors + `gate_dispatch` + record/history CLI) with shipped tier defaults in
`team-lead/stewardship/compliance-tiers.json`, fixtures in
`team-lead/scripts/fixtures/compliance/`, and the contract in
`team-lead/references/contracts/compliance.md`. Wiring the gate into dispatch is
ticket 06's job.
