# 05: Role folders — shipped defaults + project overrides

**What to build:** Onboarding by role: the team-lead skill ships default role folders
(onboarding pointers, brief templates, doorbell instructions, tool expectations per
role), and projects can override any part. A new member of a known role becomes
productive in minutes without the lead re-explaining the project.

**Blocked by:** 01 (Vocabulary seam — contracts).

**Status:** done

- [x] Shipped role folders exist for at least the roles the fleet actually uses, each
      referencing the shared vocabulary contracts (no per-role dialect)
- [x] A new member of a known role onboards from defaults (file-level demo,
      scripted in `roles/README.md`: the resolver emits the effective onboarding
      for a fake member and the emitted starter brief passes
      `validate_contracts.py brief`)
- [x] A project override wins over the shipped default where they conflict, and the
      resolution is visible (not silent)
- [x] An unknown role falls back safely (generic onboarding, flagged to the lead)
- [x] Role folder content is versioned with the agency tree

Implemented in `team-lead/roles/` (`researcher`, `implementer`, `reviewer`, `_generic`
fallback + `examples/demo-project/`) with `scripts/resolve_role.py` (stdlib-only
resolver emitting the effective onboarding plus a `RESOLUTION.md` naming every
source). Acceptance demos are scripted in `roles/README.md`.
