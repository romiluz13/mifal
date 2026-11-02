# 03: Socket adapter core — dispatch + observe

**What to build:** The lead's machine control path (ADR-0001), as a narrow complete
slice: an adapter that can **dispatch** a brief to a named member pane and **observe**
the fleet, with every safety invariant from the prototype baked in:

- One request per connection; schema-validated params (herdr silently ignores unknown
  params and substitutes dangerous defaults — this bit us once, targeting the human's
  live workspace).
- Explicit pane ids always; a missing injected pane id is a hard error, never a
  fallback to the focused pane.
- Draft guard before typing into any pane (idle ≥60 s, input box empty on two reads
  ≥10 s apart; unreadable counts as not empty).
- Receipts over waits: dispatch records the brief as sent; delivery is proven by
  durable receipts, never by return codes or timeouts.
- `--no-focus` discipline: nothing the adapter does steals the human's focus.

**Blocked by:** 00 (Version the agency tree).

**Status:** done

- [x] Against a fake-agent fleet in a scratch workspace: a brief file is dispatched to
      an explicitly named pane and the receipt artifact verifies delivery
- [x] Observe returns a fleet picture (members, states, panes) from a snapshot
- [x] Schema-invalid params are refused before anything is sent
- [x] A missing pane id is a hard error — demonstrated by attempting a dispatch without
      one and showing nothing was sent to any focused pane
- [x] Draft guard refuses to type into a pane holding a draft (simulated), and passes
      a clean pane
- [x] Focus is never stolen during any operation (verified in the pane wall)
- [x] Adapter interface is JSON in / JSON out, testable standalone (seam 2)
