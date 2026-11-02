# 04: Event loop — subscriptions + watchdog + polling floor

**What to build:** The hybrid event loop on top of the adapter core (ADR-0001, soak
verdict): events own the loop, the polling floor guards it.

- Per-pane `pane.agent_status_changed` subscriptions on read-only connections; liveness
  pings on separate connections.
- Bootstrap order on every connect/reconnect: subscribe → buffer → snapshot → apply
  buffer → stream (events never replay onto a snapshot).
- Watchdog on event silence (threshold relative to expected cadence) and explicit
  `events_lost` backpressure frames → reconnect, resubscribe, snapshot-reconcile.
- Debounce with a cap on high-frequency events; reads on transitions, not continuously.
- Polling floor: periodic snapshot reconcile on a timer, so a dead stream degrades the
  loop instead of freezing it.

**Blocked by:** 03 (Socket adapter core).

**Status:** done

- [x] Failure injection: killed subscription connection → watchdog/observe detects,
      reconnects, resubscribes, reconciles from snapshot, and the loop continues
- [x] Failure injection: slow consumer → `events_lost` handled per the documented
      recovery recipe
- [x] Failure injection: silent stream death → watchdog fires within its threshold and
      the fleet picture recovers correctly
- [x] A transition the event stream missed is still caught by the polling floor
- [x] A liveness ping never kills a subscription stream (connection discipline held
      under load)
- [x] Sustained run against the fake fleet: zero missed state transitions reconciled
      only by the floor (floor catches what events miss, events carry the fast path)
