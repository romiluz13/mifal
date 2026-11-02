# 11: Dependency validation at init

**What to build:** Mission initialization must reject dependency graphs that can
never run. Today only unknown dependency ids are refused; a task that depends on
itself, or a cycle of tasks, passes validation and then waits forever because no
member can ever satisfy the readiness rule. Self-dependencies and cycles must be
refused at init with a plain-language reason, before any record is created.

**Blocked by:** 06 (Lead loop integration).

**Status:** done (round 2 review fixes)

- [x] Refusal demo: a task listing itself in its dependencies is refused at init
- [x] Refusal demo: a dependency cycle across two or more tasks is refused at init
- [x] Control demo: a valid multi-task dependency chain still initializes

**Done (round 2):** lead.py init rejects self-dependencies and runs topological_order() DFS cycle detection; tests: test_self_dependency_is_refused_at_init, test_dependency_cycle_is_refused_at_init, test_dependency_chain_is_accepted.
