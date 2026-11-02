# 13: Bounded request deadlines

**What to build:** Every adapter wait must be bounded by a total deadline, not only
by per-read inactivity. A server that keeps trickling bytes slower than the idle
timeout can currently stretch one request past its configured duration, and the
event loop's shutdown drain can wait on a stalled snapshot forever. A request must
complete within its configured request duration or refuse with a transport error;
the shutdown drain must abandon a stalled snapshot after a bounded grace period and
report the abandonment instead of hanging.

**Blocked by:** 03 (Socket adapter core), 04 (Event loop).

**Status:** done (round 2 review fixes)

- [x] Deadline demo: a socket that trickles a response slower than the idle
      timeout is refused within the configured request duration
- [x] Control demo: a prompt, complete response still returns normally
- [x] Shutdown demo: a stalled final snapshot cannot hang the event loop past a
      bounded grace period; the abandonment is logged

**Done (round 2):** adapter.py read_response_line() total deadline; event_loop.py drain_snapshot() bounded grace; tests: test_slow_trickle_is_cut_off_at_the_total_deadline, test_fast_pong_still_returns_within_the_deadline, test_trickling_snapshot_peer_is_abandoned_within_bounded_time. The drain's abandonment log fires only when a future outlives the grace bound; in the demo the adapter deadline already bounds the read, so the loop logs the snapshot refusal instead of hanging.

**Round 3 (R-1, R-4):** the deadline now spans connect, send and read — open_request
takes the request's deadline and each phase gets only the remaining time, for
requests, subscription ACKs and resume's InspectionClient alike; an expired deadline
refuses before any socket phase. Abandonment now actually ends the wait: the
executor is shut down with shutdown(wait=False, cancel_futures=True) instead of a
context-manager join, and the connect result is fetched with a bounded wait. Tests:
test_expired_deadline_refuses_before_any_socket_phase,
test_stalled_snapshot_worker_is_abandoned_not_joined.
