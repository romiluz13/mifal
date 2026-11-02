# 15: Reread policy reconciliation

**What to build:** The binding spec promises the lead reads member output on state
transitions, not continuously, to avoid flicker; the implementation rereads every
member holding unfinished work on every lead turn, signature change or not, to
catch doorbell lines a transition read may have missed. The behavior is correct for
late doorbells, so the spec — not the code — moves: amend the transition-read story
to authorize one signature-stable reread per turn for members with unfinished work,
keeping the no-continuous-polling guarantee for everyone else, and record the
rationale at the code site so the deviation is documented, not accidental.

**Blocked by:** 06 (Lead loop integration).

**Status:** done (round 2 review fixes)

- [x] The binding story authorizes the signature-stable reread for unfinished
      members and still forbids continuous polling otherwise
- [x] The code site documents the authorized deviation and its doorbell rationale
- [x] The transition-read acceptance demos still hold: idle members are not
      reread without a transition

**Done (round 2):** spec.md story 32 amended with the authorized signature-stable reread and doorbell rationale; the debounce bullet matches; look() carries the code-site comment. The full 121-test suite (including the transition-read demos) is green.
