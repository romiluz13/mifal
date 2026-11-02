# 06: Lead loop integration — team-lead moments over the adapter

**What to build:** The full tracer bullet through every layer: the team-lead skill's
loop (look → pick → act → record → wait) running end-to-end over the adapter, the event
loop, the doorbell, and the team record, against a fake-agent fleet executing a real
micro-mission in a scratch workspace. The lead lives in a herdr pane of its own — an
agent manager, not a daemon. Model authority stays with the human: the lead recommends
and requests, never switches a member's model alone.

**Blocked by:** 01 (Vocabulary seam), 03 (Socket adapter core), 04 (Event loop).

**Status:** done

- [x] A micro-mission completes end-to-end: briefs dispatched with done-means and stop
      rules, a `HELP` doorbell answered by the lead, a `DONE` accepted only after the
      receipt is checked, the team record updated at each step
- [x] The lead picks moments by leverage (blocked member, report waiting, idle member
      with valuable work) rather than round-robin polling
- [x] Corrections get their own attempt id; a late `DONE 7` cannot close attempt 7.2
- [x] A decision outside the lead's authority escalates to the human with a
      recommendation (demo: one escalation, batched, with the lead's answer attached)
- [x] Focus is never stolen and the pane wall shows the whole mission as it happens
- [x] Zero LLM cost in the test: fake agents only; the lead's own reasoning is the only
      model spend
