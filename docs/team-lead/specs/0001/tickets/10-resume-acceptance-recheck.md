# 10: Resume acceptance re-verification

**What to build:** When the returning lead's reconciliation plan accepts a member's
completed work, the acceptance decision must be anchored to the artifact as it exists
at acceptance time, not as it existed during inspection. Between the bounded
inspection and the single first action, a member may still write to its return file;
accepting on cached digests would let changed evidence pass as current. Re-verify the
receipt digest and re-run every claim check immediately before writing the acceptance
proof; on any mismatch or failed re-check, the session holds (never accepts stale
evidence) and the next step is a fresh reconciliation id.

**Blocked by:** 09 (Resume & reconciliation lifecycle).

**Status:** done (round 2 review fixes)

- [x] Acceptance demo: the artifact changed after inspection → the first action
      holds with a durable reason; the task is not accepted
- [x] Acceptance demo: the artifact is unchanged → acceptance proceeds and the
      proof records the digest verified at acceptance time
- [x] A failed re-check never raises an unstructured crash; it becomes a durable
      hold outcome in the resume session

**Done (round 2):** resume.py apply_first accept branch re-hashes the artifact and re-runs review_receipt(); tests: test_accept_holds_when_artifact_changed_after_inspection, test_accept_holds_when_claims_fail_the_live_recheck, test_accept_on_unchanged_artifact_passes_the_live_recheck.

**Round 3 (S-3):** a member write landing between the digest and a rereading review
could make the proof digest describe bytes the review never saw. The accept path now
reads the receipt once, hashes those bytes, and passes the same bytes to
review_receipt via its new text parameter, so the proof digest is always the digest
of exactly what the review consumed. Test:
test_accept_proof_digest_describes_the_reviewed_receipt_bytes.
