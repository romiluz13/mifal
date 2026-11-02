# 09: Resume & reconciliation lifecycle

**What to build:** The returning lead's safety net (team-lead moment M1): on taking the
team again — after a break, compaction, or restart — reconcile in-flight work against
disk and live members *before* dispatching anything. Re-dispatching completed work is
the most expensive resume failure; a task line with no return may still have been sent,
so the member is inspected before resending. Member identity is verified (ids + cwd +
agent name + terminal id) before any destructive action, because pane ids are reused
after server restarts.

**Blocked by:** 06 (Lead loop integration).

**Status:** done

- [x] Resume demo 1: work completed but never reported → the lead discovers it from
      disk/live state and does not re-dispatch
- [x] Resume demo 2: work genuinely never sent → the lead dispatches it after
      inspection
- [x] Identity check demo: pane-id reuse (simulated server restart) cannot aim a close
      or prompt at the wrong pane
- [x] A single first resume action is recorded, so the next interruption resumes from
      one step
- [x] The reconcile itself is budgeted (bounded reads/waits, not a census)
