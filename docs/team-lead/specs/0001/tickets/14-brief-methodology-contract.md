# 14: Brief methodology contract

**What to build:** Generated member briefs must be able to carry the team's
methodology selection, per the brief contract and the communication reference: the
work kind (research, implementation, review, or bounded experiment) and, when the
lead selects one, the workflow — methodology, current phase, required skill paths,
scheduler, and integration owner — with the explicit inheritance rule that a
member's harness default cannot silently replace the parent's workflow. Today the
generated brief carries neither, and initialization rejects any attempt to supply
them, so a member's own harness default always wins. Small tasks stay small: the
fields are optional and omitted when not selected.

**Blocked by:** 06 (Lead loop integration).

**Status:** done (round 2 review fixes)

- [x] Contract demo: a brief generated with a kind and a workflow passes the
      team-lead brief contract validator
- [x] Inheritance demo: the workflow section states that the member inherits the
      selection and its harness default cannot silently replace it
- [x] Refusal demo: an unknown kind or a workflow without a methodology is
      refused at init
- [x] Control demo: a brief without kind or workflow is unchanged in shape

**Done (round 2):** lead.py init accepts and validates kind/workflow; brief() emits the frontmatter kind and the Workflow section with the inheritance rule; tests: test_brief_carries_kind_and_workflow_selection, test_brief_without_workflow_carries_no_workflow_section, test_init_refuses_unknown_kind_and_incomplete_workflow. Harmony: both brief shapes pass validate_contracts.py brief; selfcheck 31/31.

**Round 3 (S-1, S-2, R-3):** the validation is now structured and reachable. A
non-string kind (previously an unhashable crash) and a malformed workflow skills
list (previously a dead guard that crashed brief generation) are both plain-language
refusals at init, before any record is created. Tests:
test_malformed_kind_is_a_structured_refusal_not_a_traceback,
test_malformed_workflow_skills_is_refused_at_init.
