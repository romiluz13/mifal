# 12: Durable mission failure outcome

**What to build:** When required work ends without acceptance — a member rings
STOPPED, review exhausts the two-attempt cap, or a task is refused — the mission
must reach a durable terminal failure outcome instead of returning "wait" forever.
An unattended lead loop must terminate with a recorded, auditable failure: one
mission-failed decision with evidence naming the tasks that stopped, written to the
team record, after which further lead turns refuse until a human decides. Optional
work stopping must not fail the mission.

**Blocked by:** 06 (Lead loop integration), 11 (Dependency validation at init).

**Status:** done (round 2 review fixes)

- [x] Failure demo: a required task rings STOPPED → the next lead turn records
      mission-failed with evidence instead of waiting
- [x] Failure demo: a required task exhausts its correction attempts →
      mission-failed, not an infinite wait
- [x] Durability demo: after mission-failed, further lead turns refuse with a
      pointer to the recorded evidence
- [x] Control demo: an optional task stopping does not fail the mission

**Done (round 2):** lead.py fail_mission() + turn wiring + mission_failed guard; tests: test_stopped_ring_fails_the_mission_durably, test_second_failed_attempt_stops_without_third_dispatch (updated to the durable outcome), test_optional_stop_does_not_fail_the_mission.

**Round 3 (R-2):** review-refused is now terminal like refused/stopped. A required
task whose receipt is refused fails the mission durably instead of returning wait
forever, and an optional task that failed review no longer blocks close_mission.
Tests: test_required_receipt_refusal_fails_the_mission_durably,
test_optional_receipt_refusal_does_not_fail_the_mission.
