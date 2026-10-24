"""Only the human cuts, and reads come before the work: ticket 04, through the public validator CLI."""
import hashlib
import re
import unittest
from pathlib import Path

import test_workflow_contracts as contracts
from test_workflow_map import MAP, MapFixture


HUMAN = '"skip the spec and the tickets, just build it"'
SOURCE = "decisions.md#2026-10-17"
NO_BRANCH = contracts.WorkflowTests.default_decision


class StepFixture(unittest.TestCase):
    """The shared Matt record fixture of test_workflow_contracts, reused as a builder (its own tests do not rerun here)."""

    def setUp(self):
        self.f = contracts.WorkflowTests("setUp")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        _, pinned_spec = self.f.output("spec.md")
        _, pinned_tickets = self.f.output("issues.md")
        self.yes = f"multi-session: yes; spec: {pinned_spec}; tickets: {pinned_tickets}"
        (self.f.root / "decisions.md").write_text(f"The user, 2026-10-17:\n{HUMAN}\n")

    def record(self, checklist, decision=None, phase="review", extra=""):
        """The shared build record at `phase`, with Route decision, `extra` Workflow lines and this checklist."""
        text = self.f.workflow().replace("Phase: implement", f"Phase: {phase}")
        text = text.split("\n## Phase checklist")[0]
        text = text.replace(f"Route decision: {NO_BRANCH}\n", "").replace(
            "\nDDD:", f"\nRoute decision: {decision or NO_BRANCH}\nDDD:", 1)
        return text + extra + "\n## Phase checklist\n" + "".join(f"- [{m}] {label}\n" for m, label in checklist)

    def gate(self, text, gate="entry"):
        return self.f.run_check("workflow", text, "--gate", gate)

    def refused(self, text, *needles, gate="entry"):
        result = self.gate(text, gate)
        self.assertEqual(result.returncode, 1, result.stderr)
        for needle in needles:
            self.assertIn(needle, result.stderr)

    def passes(self, text, gate="entry"):
        result = self.gate(text, gate)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result


def steps(*done, pending=()):
    return [("x", f"{name}: done") for name in done] + [(" ", f"{name}: next") for name in pending]


class DebugFixTests(StepFixture):
    """A debug record at phase fix selects tdd: the fix is behavioural even when it reuses an existing failing test."""
    CHECKLIST = steps("Scope", "Grilling", "Reproduce", "Hypothesis", "Diagnose", pending=("Implement", "Review"))

    def fix(self, *names, phase="fix", extra="", checklist=None):
        pool = Path.home() / ".agents" / "skills"
        text = self.record(checklist or self.CHECKLIST, phase=phase, extra=extra).replace("Route: build", "Route: debug")
        text = "\n".join(l for l in text.splitlines() if not any(str(p) in l for p in self.f.phase_skills)) + "\n"
        lines = ""
        for name in names:
            path = (pool / name / "SKILL.md").resolve()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines += f"Procedure: {path}\nLoaded: {path} | worker: sha256:{digest} read event fixture-phase before work\n"
        return text.replace("\n## Phase checklist", "\n" + lines + "\n## Phase checklist", 1)

    def test_a_debug_fix_without_tdd_is_refused_with_the_existing_message(self):
        self.refused(self.fix("diagnosing-bugs"), "Phase 'fix' needs tdd SKILL.md in Procedure/Loaded")

    def test_a_debug_fix_with_tdd_passes(self):
        self.passes(self.fix("diagnosing-bugs", "tdd"))

    def test_reusing_an_existing_failing_test_still_selects_tdd(self):
        def reuse(*names):
            return self.fix(*names).replace("Next gate: test the changed behavior",
                                            "Next gate: the existing failing test goes green")
        self.refused(reuse("diagnosing-bugs"), "needs tdd SKILL.md")
        self.passes(reuse("diagnosing-bugs", "tdd"))

    def test_the_docs_only_and_coordination_exemptions_still_apply(self):
        self.passes(self.fix("diagnosing-bugs", extra="Implement: n/a: docs-only: the bug is a wrong sentence in the README\n"))
        coordination = "Implement: n/a: coordination: workers own the behavioural fix\n"
        self.refused(self.fix("diagnosing-bugs", extra=coordination), "team-lead")
        self.passes(self.fix("diagnosing-bugs", "team-lead", extra=coordination))

    def test_a_cut_of_implement_is_not_a_debug_step_so_it_cannot_lift_the_tdd_minimum(self):
        own = f"Cut: implement | {HUMAN} | {SOURCE}\n"
        for names in (("diagnosing-bugs",), ("diagnosing-bugs", "tdd")):
            with self.subTest(names=names):
                self.refused(self.fix(*names, extra=own), "'implement'", "not a step the workflow map requires")
        parent = self.f.root / "debug-state.md"
        parent.write_text(f"## Workflow\nExecutor: lead\n{own}## Phase checklist\n- [x] Scope: asked\n- [ ] Report\n")
        inherited = self.fix("diagnosing-bugs").replace("\n## Phase checklist", f"\nState: {parent}\n\n## Phase checklist", 1)
        self.refused(inherited, "'implement'", "not a step the workflow map requires")
        self.refused(self.fix("diagnosing-bugs", extra=f"Cut: review | {HUMAN} | {SOURCE}\n"), "needs tdd SKILL.md")

    def test_the_other_debug_phases_and_the_diagnosis_minimum_are_unchanged(self):
        for phase in ("reproduce", "hypothesis", "diagnose"):
            with self.subTest(phase=phase):
                self.passes(self.fix("diagnosing-bugs", phase=phase))
        self.refused(self.fix(), "Phase 'fix' needs diagnosing-bugs SKILL.md")

    def test_a_build_implement_phase_keeps_its_own_minimum(self):
        self.refused(self.record(steps("Scope", "Grilling", pending=("Implement",)), phase="implement").replace(
            str(self.f.phase_skills[1]), "/nonexistent"), "needs tdd SKILL.md")


class RequiredStepTests(StepFixture):
    def test_a_completed_sequence_missing_a_required_step_is_refused_naming_it(self):
        skipped = steps("Scope", "Grilling", "Implement", pending=("Review",))
        self.refused(self.record(skipped, self.yes), "to-spec", "to-tickets", "workflow map")
        self.refused(self.record(steps("Scope", "Implement"), NO_BRANCH), "'grilling'")

    def test_every_gate_and_the_brief_check_refuse_it(self):
        text = self.record(steps("Scope", "Implement"), NO_BRANCH)
        result = self.f.run_check("brief", self.f.brief() + text, "--matt")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("'grilling'", result.stderr)
        self.refused(text, "'grilling'", gate="review")

    def test_accept_holds_every_step_and_leaves_only_the_report_open(self):
        done = steps("Scope", "Grilling", "Implement", "Review") + [(" ", "Report")]
        result = self.gate(self.record(done, phase="report"), "accept")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("'retro'", result.stderr)

    def test_a_sourced_cut_passes_the_same_record(self):
        skipped = steps("Scope", "Grilling", "Implement", pending=("Review",))
        cut = f"Cut: to-spec, to-tickets | {HUMAN} | {SOURCE}\n"
        self.passes(self.record(skipped, self.yes, extra=cut))

    def test_a_cut_covers_only_the_steps_it_names(self):
        skipped = steps("Scope", "Implement")
        cut = f"Cut: grilling | {HUMAN} | {SOURCE}\n"
        self.passes(self.record(skipped, NO_BRANCH, extra=cut))
        wrong = f"Cut: to-spec | {HUMAN} | {SOURCE}\n"
        self.refused(self.record(skipped, NO_BRANCH, extra=wrong), "'grilling'")

    def test_a_cut_without_a_human_quote_and_source_is_refused(self):
        skipped = steps("Scope", "Grilling", "Implement", pending=("Review",))
        for label, line in (("no quote or source", "Cut: to-spec, to-tickets"),
                            ("no quote", f"Cut: to-spec, to-tickets | {SOURCE}"),
                            ("no source", f"Cut: to-spec, to-tickets | {HUMAN}"),
                            ("empty source", f"Cut: to-spec, to-tickets | {HUMAN} |"),
                            ("placeholder quote", f"Cut: to-spec, to-tickets | TBD | {SOURCE}"),
                            ("placeholder source", f"Cut: to-spec, to-tickets | {HUMAN} | <where>"),
                            ("no steps", f"Cut: | {HUMAN} | {SOURCE}")):
            with self.subTest(label):
                self.refused(self.record(skipped, self.yes, extra=line + "\n"),
                             "Cut needs the human's quote and a source pointer")

    def test_a_cut_names_a_step_the_map_requires(self):
        skipped = steps("Scope", "Grilling", "Implement")
        self.refused(self.record(skipped, self.yes, extra=f"Cut: banana | {HUMAN} | {SOURCE}\n"),
                     "'banana'", "not a step the workflow map requires")

    def test_a_cut_reaches_the_independent_minima_it_names(self):
        # Grilling, implement with tdd, and code-review each have their own hard check; the human's cut must reach them.
        def without(text, *needles):
            return "\n".join(l for l in text.splitlines() if not any(n in l for n in needles)) + "\n"
        impl = [str(p) for p in self.f.phase_skills[:2]]
        review = [str(self.f.phase_skills[2])]
        for step, phase, checklist, drop in (
                ("grilling", "implement", steps("Scope", "Implement"), [self.f.grilling.strip()]),
                ("implement", "implement", steps("Scope", "Grilling"), impl),
                ("review", "review", steps("Scope", "Grilling", "Implement"), review)):
            with self.subTest(step):
                bare = without(self.record(checklist, phase=phase), *drop)
                self.refused(bare, gate="entry")
                cut = f"Cut: {step} | {HUMAN} | {SOURCE}\n"
                self.passes(without(self.record(checklist, phase=phase, extra=cut), *drop))

    def test_a_cut_of_retro_lifts_the_accept_hold(self):
        base = self.f.completed_workflow()
        text = "\n".join(line for line in base.splitlines() if not line.startswith("Retro:")) + "\n"
        self.refused(text, "Retro", gate="accept")
        cut = text.replace("\n## Phase checklist", f"\nCut: retro | {HUMAN} | {SOURCE}\n\n## Phase checklist", 1)
        self.passes(cut, gate="accept")

    def test_a_cut_of_the_spec_and_tickets_lifts_the_pin_hold(self):
        later = f"multi-session: yes; spec: {self.f.root}/spec-later.md; tickets: {self.f.root}/tickets-later.md"
        text = self.record(steps("Scope", "Grilling"), later, phase="implement")
        self.refused(text, "holds implementation until the pinned spec and tickets exist")
        cut = f"Cut: to-spec, to-tickets | {HUMAN} | {SOURCE}\n"
        self.passes(self.record(steps("Scope", "Grilling"), later, phase="implement", extra=cut))
        one = f"Cut: to-spec | {HUMAN} | {SOURCE}\n"
        self.refused(self.record(steps("Scope", "Grilling"), later, phase="implement", extra=one),
                     "the tickets are unpinned")

    def test_still_pending_later_steps_are_not_skips(self):
        self.passes(self.record(steps("Scope", "Grilling", pending=("Implement", "Review", "Retro")),
                                phase="implement"))
        self.passes(self.record(steps("Scope", "Grilling", "Implement", pending=("Review",)), phase="review"),
                    gate="entry")
        self.passes(self.record(steps("Scope"), phase="plan"))

    def test_a_step_listed_but_unfinished_while_a_later_one_is_done_is_a_skip(self):
        out_of_order = [("x", "Scope: asked"), (" ", "Grilling: later"), ("x", "Implement: built")]
        self.refused(self.record(out_of_order, NO_BRANCH), "'grilling'")

    def test_the_branch_must_be_recorded_before_the_steps_that_depend_on_it(self):
        text = self.record(steps("Scope", "Grilling", "Implement")).replace(
            f"Route decision: {NO_BRANCH}\n", "")
        self.refused(text, "Route decision", "not recorded")

    def test_a_branch_recorded_in_the_parent_state_counts(self):
        parent = self.f.root / "state.md"
        parent.write_text(f"## Workflow\nExecutor: lead\nRoute decision: {NO_BRANCH}\n"
                          f"Cut: grilling | {HUMAN} | {SOURCE}\n"
                          "## Phase checklist\n- [x] Scope: asked\n- [x] Implement: built\n- [ ] Report\n")
        text = self.record(steps("Scope", "Implement")).replace(f"Route decision: {NO_BRANCH}\n", "")
        text = text.replace("\n## Phase checklist", f"\nState: {parent}\n\n## Phase checklist", 1)
        self.passes(text.replace(self.f.grilling, ""))
        parent.write_text(parent.read_text().replace(f"Cut: grilling | {HUMAN} | {SOURCE}\n", ""))
        self.refused(text.replace(self.f.grilling, ""), "'grilling'")

    def test_a_closed_receipt_is_not_regated(self):
        receipt = ("\n## Return\nCloses: 1\n### Result\nBuilt the fixture.\n### Claims\n"
                   "- behavior: passed at the fixture digest\n### Evidence\nTest trace.\n" + self.f.load_lines())
        text = self.f.brief() + self.record(steps("Scope", "Implement"), NO_BRANCH) + receipt
        result = self.f.run_check("receipt", text, "--matt")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_other_routes_read_their_own_steps_from_the_map(self):
        review = self.record(steps("Scope", "Review"), phase="review").replace("Route: build", "Route: review")
        self.refused(review, "'inspect'", "route review")

    def test_the_review_gate_holds_every_step_before_review(self):
        self.refused(self.record(steps("Scope", pending=("Grilling", "Implement")), NO_BRANCH, phase="implement"),
                     "'grilling'", gate="review")

    def test_the_report_and_deliver_phases_hold_every_step(self):
        self.refused(self.record(steps("Scope", "Grilling", "Implement"), NO_BRANCH, phase="report"), "'review'")
        plan = self.record(steps("Scope", "Inspect", "Resolve", "Plan"), phase="deliver").replace(
            "Route: build", "Route: plan")
        plan = "\n".join(l for l in plan.splitlines() if not l.startswith("Route decision:")) + "\n"
        self.refused(plan, "'review'", "route plan")

    def test_the_current_phase_alone_makes_no_step_due(self):
        self.passes(self.record(steps("Scope", pending=("Grilling", "Implement", "Review")), NO_BRANCH, phase="review"))


class LateReadTests(StepFixture):
    START = "Check: start implement | passed | brief --matt exit 0 at:2026-10-17T10:00:00Z\n"

    def stamped(self, when, start=True, which=None, form="at:{}"):
        """The implement-phase record with every Loaded line stamped `when`, or only the one naming `which`."""
        text = self.record(steps("Scope", "Grilling", pending=("Implement",)), NO_BRANCH + " at:2026-10-17T09:00:00Z",
                           phase="implement", extra=self.START if start else "")
        out = []
        for line in text.splitlines():
            if line.startswith("Loaded:") and (which is None or which in line):
                line += " " + form.format(when)
            out.append(line)
        return "\n".join(out) + "\n"

    def test_a_read_stamped_after_the_phase_start_check_is_refused(self):
        self.refused(self.stamped("2026-10-17T10:05:00Z", which="/tdd/"), "tdd", "after", "start Check")

    def test_a_read_stamped_before_the_phase_start_check_passes(self):
        self.passes(self.stamped("2026-10-17T09:59:00Z"))
        self.passes(self.stamped("2026-10-17T10:00:00Z"))

    def test_the_earliest_start_check_is_the_one_a_read_is_held_to(self):
        later = self.START.replace("10:00:00", "11:00:00")
        text = self.stamped("2026-10-17T10:30:00Z").replace(self.START, self.START + later)
        self.refused(text, "after", "start Check")

    def test_unknown_timing_stays_unverified_not_refused(self):
        result = self.passes(self.stamped("2026-10-17T09:00:00Z", which="/tdd/"))
        self.assertIn("unverified", result.stderr)
        result = self.passes(self.stamped("2026-10-17T09:00:00Z", start=False))
        self.assertIn("unverified", result.stderr)

    def test_prose_that_says_at_is_not_a_stamp(self):
        text = self.stamped("2026-10-17T09:00:00Z").replace("before work", "before work, looked at: the whole body", 1)
        self.passes(text)

    def test_a_malformed_stamp_is_refused(self):
        for bad in ("2026-13-45T99:00Z", "2026-10-17", "2026-10-17T10:00:00+02:00"):
            with self.subTest(bad):
                self.refused(self.stamped(bad, which="/tdd/"), "at:", "ISO-8601")

    def test_a_stamp_is_read_whatever_its_case_or_spacing(self):
        for form in ("at: {}", "AT:{}", "At:  {}", "at:\t{}"):
            with self.subTest(form):
                self.refused(self.stamped("2026-10-17T10:30:00Z", which="/tdd/", form=form), "tdd", "after")
                self.passes(self.stamped("2026-10-17T09:30:00Z", which="/tdd/", form=form))

    def test_a_near_miss_stamp_is_parsed_or_refused_never_unstamped(self):
        for bad in ("2026-10-17T10:30:00Z)", "10:30", "2026-10-17 10:30"):
            with self.subTest(bad):
                result = self.gate(self.stamped(bad, which="/tdd/", form="(at: {}"))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("ISO-8601", result.stderr)

    def test_the_receipt_check_holds_a_workers_late_read(self):
        text = self.stamped("2026-10-17T09:00:00Z")
        late = text.replace("read event fixture-phase before work at:2026-10-17T09:00:00Z",
                            "read event fixture-phase before work at:2026-10-17T12:00:00Z", 1)
        self.assertNotEqual(text, late)
        receipt = ("\n## Return\nCloses: 1\n### Result\nBuilt the fixture.\n### Claims\n"
                   "- behavior: passed at the fixture digest\n### Evidence\nTest trace.\n")
        loads = [line for line in late.splitlines() if line.startswith("Loaded:")]
        check = self.f.run_check("receipt", self.f.brief() + late.replace("\n".join(loads) + "\n", "") + receipt
                                 + "\n".join(loads) + "\n", "--matt")
        self.assertEqual(check.returncode, 1, check.stderr)
        self.assertIn("after", check.stderr)


class WorkerUnderParentTests(StepFixture):
    """Correction 24.2, ruling 1: a parent State's checklist is the parent's, and its steps are the parent route's."""

    def parent(self, name="lead-state.md", route="build", labels=None, decision=None):
        labels = labels or ("Scope: asked", "Grilling: done", "To-spec: done", "To-tickets: done",
                            "Implement: built", "Review: first review done")
        path = self.f.root / name
        path.write_text(f"## Workflow\nExecutor: lead\nRoute: {route}\nRoute decision: {decision or self.yes}\n"
                        "## Phase checklist\n" + "".join(f"- [x] {label}\n" for label in labels)
                        + "- [ ] Retro\n- [ ] Report\n")
        return path

    def worker(self, parent, route="review", phase="review", checklist=None):
        """A worker record under `parent`: no Route decision of its own, its own checklist only when given."""
        text = self.record(checklist or steps("Scope"), phase=phase).replace("Route: build", f"Route: {route}")
        text = "\n".join(l for l in text.splitlines() if not l.startswith("Route decision:")) + "\n"
        head, _, tail = text.partition("\n## Phase checklist")
        return f"{head}State: {parent}\n" + (f"\n## Phase checklist{tail}" if checklist else "")

    def test_a_review_worker_is_not_held_to_the_parents_build_steps_or_the_reverse(self):
        text = self.worker(self.parent())
        self.passes(text)
        result = self.f.run_check("brief", self.f.brief() + text, "--matt")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_worker_without_a_checklist_of_its_own_gets_no_step_check(self):
        mislabelled = self.parent(labels=("Scope: asked", "Review: first review done"))
        self.passes(self.worker(mislabelled))

    def test_a_workers_own_checklist_is_checked_against_the_workers_route(self):
        text = self.worker(self.parent(), checklist=steps("Scope", "Review"))
        self.refused(text, "'inspect'", "route review")
        done = steps("Scope", "Inspect", "Review", "Substantiate")
        self.passes(self.worker(self.parent(), checklist=done))


class ExactLabelTests(StepFixture):
    """Correction 24.2, ruling 4: a label counts as the step only when its words before ':' are the step's name."""

    def research(self, label):
        done = ["Scope: q", "Source: plan", "Investigate: read", "Synthesize: written", label, "Verify: ok"]
        text = self.record([("x", name) for name in done], phase="verify").replace("Route: build", "Route: research")
        return "\n".join(l for l in text.splitlines() if not l.startswith("Route decision:")) + "\n"

    def test_a_label_that_announces_a_skip_does_not_count(self):
        for label, text in (
                ("grilling skipped", self.record([("x", "Scope: asked"), ("x", "Grilling skipped: no time"),
                                                  ("x", "Implement: built")], NO_BRANCH)),
                ("scope skipped", self.record([("x", "Scope skipped"), ("x", "Grilling: done"),
                                               ("x", "Implement: built")], NO_BRANCH)),
                ("to-spec skipped", self.record([("x", "Scope: asked"), ("x", "Grilling: done"),
                                                 ("x", "To-spec skipped: the user never asked"), ("x", "To-tickets skipped"),
                                                 ("x", "Implement: built")], self.yes)),
                ("review later", self.research("Review later: no time"))):
            with self.subTest(label):
                self.refused(text, f"'{label.split()[0]}'")

    def test_the_whole_label_or_its_words_before_the_colon_count(self):
        self.passes(self.research("Review"))
        self.passes(self.research("review: the claims were checked"))
        self.passes(self.record([("x", "Scope"), ("x", "grilling"), ("x", "Implement: built")], NO_BRANCH))
        self.passes(self.record([("x", "Scope: asked"), ("x", "Grilling: done"), ("x", "To-spec: done"),
                                 ("x", "To tickets: ok"), ("x", "Implement: built")], self.yes))

    def test_a_longer_label_with_extra_words_does_not_count(self):
        self.refused(self.research("Review of the claims: done"), "'review'")


class ReadPhaseTests(StepFixture):
    """Correction 24.2, ruling 2: a stamped read is held to the start Check of the phase that needs its body."""
    START_IMPLEMENT = "Check: start implement | passed | brief --matt exit 0 at:2026-10-17T10:00:00Z\n"
    START_REVIEW = "Check: start review | passed | review gate exit 0 at:2026-10-17T11:00:00Z\n"
    EARLY = "2026-10-17T09:00:00Z"

    def review_record(self, reads, checks):
        """A record at Phase review whose Loaded lines are stamped per `reads` ({path fragment: time})."""
        text = self.record(steps("Scope", "Grilling", "Implement", pending=("Review",)),
                           NO_BRANCH + " at:2026-10-17T09:00:00Z", phase="review", extra="".join(checks))
        out = []
        for line in text.splitlines():
            if line.startswith("Loaded:"):
                line += f" at:{next((when for key, when in reads.items() if key in line), self.EARLY)}"
            out.append(line)
        return "\n".join(out) + "\n"

    def test_a_late_read_stays_refused_after_the_record_moves_on(self):
        late = {"/tdd/": "2026-10-17T10:30:00Z"}
        self.refused(self.review_record(late, [self.START_IMPLEMENT, self.START_REVIEW]), "tdd", "'implement'", "after")
        self.refused(self.review_record(late, [self.START_IMPLEMENT]), "tdd", "'implement'", "after")

    def test_a_read_is_held_only_to_its_own_phase(self):
        # The review body read after the implement start but before the review start is on time.
        self.passes(self.review_record({"/code-review/": "2026-10-17T10:30:00Z"},
                                       [self.START_IMPLEMENT, self.START_REVIEW]))
        self.refused(self.review_record({"/code-review/": "2026-10-17T11:30:00Z"},
                                        [self.START_IMPLEMENT, self.START_REVIEW]), "code-review", "'review'", "after")

    def test_router_and_entry_bodies_are_held_to_the_earliest_start_of_any_phase(self):
        for body in ("/ask-matt/", "/engineering-workflow/"):
            with self.subTest(body):
                self.refused(self.review_record({body: "2026-10-17T10:30:00Z"},
                                                [self.START_IMPLEMENT, self.START_REVIEW]), body.strip("/"), "after")
                self.passes(self.review_record({body: "2026-10-17T09:30:00Z"},
                                               [self.START_IMPLEMENT, self.START_REVIEW]))

    def test_a_phase_with_no_stamped_start_check_leaves_its_reads_unverified(self):
        result = self.passes(self.review_record({"/tdd/": "2026-10-17T10:30:00Z"}, [self.START_REVIEW]))
        self.assertIn("unverified", result.stderr)


class ReadRuleTests(StepFixture):
    """Correction 28.2, part 1: a body is on time when one read of it precedes the earliest start Check of the step its
    map row governs; a later reload never makes it late; a start Check names a step of the map."""
    EARLY, SECOND = "2026-10-17T09:59:00Z", "2026-10-17T11:00:00Z"
    STAMPED = " at:2026-10-17T09:00:00Z"

    @staticmethod
    def start(step, when):
        return f"Check: start {step} | passed | gate exit 0 at:{when}\n"

    def pool_body(self, name):
        path = (Path.home() / ".agents" / "skills" / name / "SKILL.md").resolve()
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def rec(self, reads, checks, phase="implement", checklist=None, decision=None, extra_bodies=()):
        """The shared record with `checks`; `reads` maps a path fragment to the times of its Loaded lines (default
        EARLY); `extra_bodies` maps a pool skill to its read times, with its Procedure line."""
        text = self.record(checklist or steps("Scope", "Grilling", pending=("Implement",)),
                           decision or NO_BRANCH + self.STAMPED, phase=phase, extra="".join(checks))
        for name, times in dict(extra_bodies).items():
            path, digest = self.pool_body(name)
            lines = "".join(f"Loaded: {path} | worker: sha256:{digest} read event {name}-{i}\n" for i, _ in enumerate(times))
            text = text.replace("\nDDD:", f"\nProcedure: {path}\n{lines}DDD:", 1)
            reads = {**reads, f"/{name}/": times}
        out, seen = [], set()
        for line in text.splitlines():
            key = next((k for k in reads if k in line.split("|")[0]), None) if line.startswith("Loaded:") else None
            if not line.startswith("Loaded:"):
                out.append(line)
            elif key is None or key in seen:
                out.append(f"{line} at:{reads[key][0] if key else self.EARLY}")
            else:
                seen.add(key)
                out.extend(f"{line} at:{when}" for when in reads[key])
        return "\n".join(out) + "\n"

    def test_a_reload_after_the_work_began_does_not_make_the_earlier_read_late(self):
        start = [self.start("implement", "2026-10-17T10:00:00Z")]
        for body in ("/engineering-workflow/", "/ask-matt/", "/tdd/"):
            with self.subTest(body):
                self.passes(self.rec({body: [self.EARLY, self.SECOND]}, start))

    def test_a_body_whose_only_read_is_after_the_start_check_stays_refused(self):
        start = [self.start("implement", "2026-10-17T10:00:00Z")]
        for body in ("/engineering-workflow/", "/ask-matt/", "/tdd/"):
            with self.subTest(body):
                self.refused(self.rec({body: [self.SECOND]}, start), body.strip("/"), "after", "start Check")

    def test_the_reload_is_judged_whatever_the_order_of_its_lines(self):
        start = [self.start("implement", "2026-10-17T10:00:00Z")]
        self.passes(self.rec({"/tdd/": [self.SECOND, self.EARLY]}, start))

    def test_a_start_check_must_name_a_step_of_the_map(self):
        for bad in ("entry", "implemen", "gate", "spec", "implement now"):
            with self.subTest(bad):
                self.refused(self.rec({}, [self.start(bad, "2026-10-17T10:00:00Z")]), "start Check", "unknown step",
                             f"'{bad}'")
        for good in ("scope", "grilling", "to-spec", "to-tickets", "implement", "review", "retro", "report",
                     "inspect", "resolve", "reproduce"):
            with self.subTest(good):
                self.passes(self.rec({}, [self.start(good, "2026-10-17T10:00:00Z")]))

    def test_an_unknown_step_does_not_disable_the_late_read_rule(self):
        # The unnamed start Check used to leave every read unverified (probe B1).
        self.refused(self.rec({"/ask-matt/": [self.SECOND]}, [self.start("entry", "2026-10-17T10:00:00Z")]),
                     "unknown step")

    def spec_record(self, read_at, checks, phase="plan", checklist=None):
        return self.rec({}, checks, phase=phase, decision=self.yes + self.STAMPED, extra_bodies={"to-spec": [read_at]},
                        checklist=checklist or steps("Scope", "Grilling", pending=("To-spec", "To-tickets", "Implement")))

    def test_the_lead_may_read_to_spec_after_the_griller_dispatch(self):
        # F31-1: start plan logged at the griller dispatch; to-spec is read once the griller closes.
        plan = [self.start("plan", "2026-10-17T10:00:00Z")]
        self.passes(self.spec_record("2026-10-17T11:00:00Z", plan))
        self.passes(self.spec_record("2026-10-17T11:00:00Z", plan + [self.start("to-spec", "2026-10-17T11:30:00Z")]))

    def test_to_spec_is_held_to_the_start_check_of_to_spec(self):
        plan = [self.start("plan", "2026-10-17T10:00:00Z")]
        late = plan + [self.start("to-spec", "2026-10-17T10:30:00Z")]
        self.refused(self.spec_record("2026-10-17T11:00:00Z", late), "to-spec", "after", "'to-spec'")
        # the refusal stays once the record moves on to implement
        done = steps("Scope", "Grilling", "To-spec", "To-tickets", pending=("Implement",))
        moved = late + [self.start("implement", "2026-10-17T13:00:00Z")]
        self.refused(self.spec_record("2026-10-17T11:00:00Z", moved, "implement", done), "to-spec", "'to-spec'")
        self.passes(self.spec_record("2026-10-17T10:15:00Z", moved, "implement", done))

    def test_to_spec_read_between_the_griller_and_the_builder_passes_after_the_phase_moves_on(self):
        # E3: start plan 10:00, to-spec read 11:00, start to-spec 11:30, start implement 13:00.
        done = steps("Scope", "Grilling", "To-spec", "To-tickets", pending=("Implement",))
        checks = [self.start("plan", "2026-10-17T10:00:00Z"), self.start("to-spec", "2026-10-17T11:30:00Z"),
                  self.start("implement", "2026-10-17T13:00:00Z")]
        self.passes(self.spec_record("2026-10-17T11:00:00Z", checks, "implement", done))

    def test_the_grilling_bodies_govern_grilling_not_the_plan_phase(self):
        grill = {"grill-with-docs": ["2026-10-17T11:00:00Z"]}
        plan = [self.start("plan", "2026-10-17T10:00:00Z")]
        self.passes(self.rec({}, plan, "plan", extra_bodies=grill))
        self.refused(self.rec({}, plan + [self.start("grilling", "2026-10-17T10:30:00Z")], "plan", extra_bodies=grill),
                     "grill-with-docs", "'grilling'", "after")
        self.passes(self.rec({}, plan + [self.start("grilling", "2026-10-17T11:30:00Z")], "plan", extra_bodies=grill))

    def test_tdd_governs_implement_alone_not_the_other_phases_of_its_map_row(self):
        # The tdd row names implement and remediate; a remediate start Check logged first does not hold the read.
        checks = [self.start("remediate", "2026-10-17T10:00:00Z"), self.start("implement", "2026-10-17T12:00:00Z")]
        self.passes(self.rec({"/tdd/": ["2026-10-17T11:00:00Z"]}, checks))
        self.refused(self.rec({"/tdd/": ["2026-10-17T12:30:00Z"]}, checks), "tdd", "'implement'", "after")

    def test_tdd_and_implement_govern_implement_and_code_review_governs_review(self):
        start = [self.start("implement", "2026-10-17T10:00:00Z"), self.start("review", "2026-10-17T12:00:00Z")]
        done = steps("Scope", "Grilling", "Implement", pending=("Review",))
        self.passes(self.rec({}, start, "review", done, extra_bodies={"code-review": ["2026-10-17T11:00:00Z"]}))
        self.refused(self.rec({}, start, "review", done, extra_bodies={"code-review": ["2026-10-17T12:30:00Z"]}),
                     "code-review", "'review'")

    def test_writing_for_agents_governs_retro_whatever_the_records_phase(self):
        # Its map row names no phase before the parenthesis, so without a governed step it fell back to Phase.
        start = [self.start("implement", "2026-10-17T10:00:00Z"), self.start("review", "2026-10-17T12:00:00Z"),
                 self.start("retro", "2026-10-17T13:00:00Z")]
        done = steps("Scope", "Grilling", "Implement", pending=("Review",))
        self.passes(self.rec({}, start, "review", done, extra_bodies={"writing-for-agents": ["2026-10-17T12:30:00Z"]}))
        self.refused(self.rec({}, start, "review", done, extra_bodies={"writing-for-agents": ["2026-10-17T13:30:00Z"]}),
                     "writing-for-agents", "'retro'")


class BranchOrderTests(StepFixture):
    """Correction 24.2, ruling 3: the branch is the parent's, and it is recorded before execution began."""
    START = "Check: start implement | passed | brief --matt exit 0 at:2026-10-17T10:00:00Z\n"

    def with_decision(self, decision, extra=START):
        done = ("Scope", "Grilling") + (("To-spec", "To-tickets") if "yes" in decision else ()) + ("Implement",)
        return self.record(steps(*done, pending=("Review",)), decision, phase="implement", extra=extra)

    def test_a_worker_may_not_override_the_parents_branch(self):
        parent = self.f.root / "parent-yes.md"
        parent.write_text(f"## Workflow\nExecutor: lead\nRoute decision: {self.yes}\n"
                          "## Phase checklist\n- [x] Scope: asked\n- [ ] Report\n")

        def worker(decision):
            text = self.record(steps("Scope"), decision, phase="plan")
            return text.replace("\n## Phase checklist", f"\nState: {parent}\n\n## Phase checklist", 1)
        self.refused(worker("multi-session: no; reason: the worker thinks it is small"),
                     "Route decision", "differs from the parent State's")
        self.passes(worker(self.yes))

    def test_a_branch_stamped_before_the_implement_start_check_passes(self):
        self.passes(self.with_decision(NO_BRANCH + " at:2026-10-17T09:59:00Z"))
        self.passes(self.with_decision(NO_BRANCH + " at:2026-10-17T10:00:00Z"))
        self.passes(self.with_decision(self.yes + " at:2026-10-17T09:00:00Z"))

    def test_a_branch_recorded_after_execution_began_is_refused(self):
        self.refused(self.with_decision(NO_BRANCH + " at:2026-10-17T10:30:00Z"),
                     "Route decision", "recorded after execution began")
        self.refused(self.with_decision("multi-session: no; reason: changed my mind at:2026-10-17T12:00:00Z"),
                     "recorded after execution began")

    def test_an_unstamped_branch_on_a_record_with_stamped_start_checks_is_refused(self):
        self.refused(self.with_decision(NO_BRANCH), "Route decision", "at:")
        self.refused(self.with_decision(NO_BRANCH + " at:10:30"), "Route decision", "ISO-8601")

    def test_without_stamped_start_checks_an_unstamped_branch_still_passes(self):
        self.passes(self.with_decision(NO_BRANCH, extra=""))


class CutSourceTests(StepFixture):
    """Correction 24.2, ruling 7: a path source holds the quote; a cut names steps of the record's route and branch."""
    SKIPPED = steps("Scope", "Grilling", "Implement", pending=("Review",))

    def cut(self, line, decision=None, checklist=None, phase="review"):
        return self.record(checklist or self.SKIPPED, decision or self.yes, phase=phase, extra=line + "\n")

    def test_a_path_source_must_exist_and_hold_the_quote(self):
        names = "to-spec, to-tickets"
        self.passes(self.cut(f"Cut: {names} | {HUMAN} | {SOURCE}"))
        self.passes(self.cut(f"Cut: {names} | {HUMAN} | {self.f.root}/decisions.md"))
        self.passes(self.cut(f"Cut: {names} | {HUMAN} | the user said it in the chat on 2026-10-17"))
        self.refused(self.cut(f"Cut: {names} | {HUMAN} | {self.f.root}/no-such-file.md"), "no-such-file.md", "unavailable")
        self.refused(self.cut(f"Cut: {names} | {HUMAN} | missing/notes.md#top"), "notes.md", "unavailable")
        (self.f.root / "other.md").write_text("The user: build all of it, no cuts\n")
        self.refused(self.cut(f"Cut: {names} | {HUMAN} | other.md#2026-10-17"), "other.md", "does not contain the quote")

    def test_a_cut_names_steps_of_the_records_own_route_and_branch(self):
        human = f"| {HUMAN} | {SOURCE}"
        self.refused(self.cut(f"Cut: to-spec {human}", NO_BRANCH, steps("Scope", "Grilling", "Implement")),
                     "'to-spec'", "not a step the workflow map requires")
        self.refused(self.cut(f"Cut: resolve {human}", NO_BRANCH, steps("Scope", "Grilling", "Implement")), "'resolve'")
        self.refused(self.cut(f"Cut: substantiate {human}", NO_BRANCH, steps("Scope", "Grilling", "Implement")),
                     "'substantiate'")
        self.passes(self.cut(f"Cut: to-spec {human}", self.yes, steps("Scope", "Grilling", "To-tickets", "Implement")))

    def test_a_plan_route_cut_of_resolve_lifts_the_grilling_line(self):
        plan = self.record(steps("Scope", "Inspect"), phase="resolve").replace("Route: build", "Route: plan")
        plan = "\n".join(l for l in plan.splitlines()
                         if not l.startswith(("Route decision:", "Grilling:"))) + "\n"
        self.refused(plan, "A plan record at resolve or later needs a Grilling line")
        cut = plan.replace("\n## Phase checklist", f"\nCut: resolve | {HUMAN} | {SOURCE}\n\n## Phase checklist", 1)
        self.passes(cut)


def without(text, *needles):
    """`text` minus every line that holds one of `needles`."""
    return "\n".join(l for l in text.splitlines() if not any(n in l for n in needles)) + "\n"


class WorkerCutFixture(StepFixture):
    """A worker's brief and return, checked at the gate and at `receipt --matt`, with a Cut in its brief or its parent State."""
    RETURN = ("\n## Return\nCloses: 1\n### Result\nBuilt the fixture.\n### Claims\n"
              "- behavior: passed at the fixture digest\n### Evidence\nTest trace.\n")

    def receipt(self, record, forged=""):
        text = self.f.brief() + record + self.RETURN + forged + self.f.load_lines()
        return self.f.run_check("receipt", text, "--matt")

    def minima(self):
        """(step, phase, the record lines that declare the body or line the worker owes when that step is not cut)"""
        impl = [str(p) for p in self.f.phase_skills[:2]]
        return (("grilling", "implement", [self.f.grilling.strip()]),
                ("implement", "implement", impl),
                ("review", "review", [str(self.f.phase_skills[2])]))

    def worker(self, step, phase, drop, extra="", state=None):
        record = self.record(steps("Scope", "Grilling", "Implement"), NO_BRANCH, phase=phase,
                             extra=extra + (f"State: {state}\n" if state else ""))
        return without(record, *drop)

    def parent_holding(self, cut, name="parent"):
        """A parent State in its own folder that holds `cut` and the quote it cites (`only-here.log`)."""
        folder = self.f.root / name
        folder.mkdir()
        (folder / "only-here.log").write_text(f"The user, 2026-10-17:\n{HUMAN}\n")
        state = folder / "state.md"
        state.write_text(f"## Workflow\nExecutor: lead\nRoute decision: {NO_BRANCH}\n{cut}\n"
                         "## Phase checklist\n- [x] Scope: asked\n- [ ] Report\n")
        return state

    def seams(self):
        """(name, check) for the two places a worker's Cut is read: the entry gate on its record and its receipt."""
        return (("gate", lambda record: self.gate(record)), ("receipt", self.receipt))


class ReceiptCutTests(WorkerCutFixture):
    """Correction 27.2, ruling 2 (F30-2): `receipt --matt` honours the sourced Cut its brief or its parent State holds,
    for the minima the gate waives; a cut that lifts nothing for the worker changes nothing."""

    def test_a_receipt_honours_a_sourced_cut_for_each_minimum_it_names(self):
        for step, phase, drop in self.minima():
            with self.subTest(step):
                held = self.receipt(self.worker(step, phase, drop))
                self.assertEqual(held.returncode, 1, held.stderr)
                result = self.receipt(self.worker(step, phase, drop, extra=f"Cut: {step} | {HUMAN} | {SOURCE}\n"))
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_receipt_honours_a_sourced_cut_the_parent_state_holds(self):
        for step, phase, drop in self.minima():
            with self.subTest(step):
                state = self.parent_holding(f"Cut: {step} | {HUMAN} | only-here.log", name=f"parent-{step}")
                result = self.receipt(self.worker(step, phase, drop, state=state))
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_receipt_does_not_honour_a_cut_the_gate_would_refuse(self):
        for label, line, needle in (
                ("no source", f"Cut: grilling | {HUMAN}", "Cut needs the human's quote and a source pointer"),
                ("placeholder quote", f"Cut: grilling | TBD | {SOURCE}", "Cut needs the human's quote and a source pointer"),
                ("a source that is not there", f"Cut: grilling | {HUMAN} | missing/notes.md", "unavailable"),
                ("a source without the quote", f"Cut: grilling | {HUMAN} | other.md", "does not contain the quote"),
                ("a step the map does not require", f"Cut: banana | {HUMAN} | {SOURCE}", "not a step the workflow map requires")):
            with self.subTest(label):
                (self.f.root / "other.md").write_text("The user: build all of it, no cuts\n")
                step, phase, drop = self.minima()[0]
                result = self.receipt(self.worker(step, phase, drop, extra=line + "\n"))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(needle, result.stderr)
                self.assertIn("Grilling needs", result.stderr)

    def test_a_cut_in_the_workers_return_is_not_a_cut(self):
        step, phase, drop = self.minima()[0]
        result = self.receipt(self.worker(step, phase, drop), forged=f"Cut: grilling | {HUMAN} | {SOURCE}\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Grilling needs", result.stderr)

    def test_a_cut_that_lifts_nothing_for_the_worker_changes_nothing(self):
        # Retro and the spec steps are due at the parent's accept gate, never at a worker's receipt; review is not due
        # at the implement phase. A valid cut of them leaves the receipt verdict and its words as they were.
        for label, step, phase, drop in (("passing receipt", "retro", "implement", []),
                                         ("passing receipt, review cut before the review phase", "review", "implement", []),
                                         ("refused receipt", "retro", "implement", [self.f.grilling.strip()]),
                                         ("refused receipt, implement cut at the review phase", "implement", "review",
                                          [str(self.f.phase_skills[2])])):
            with self.subTest(label):
                plain = self.receipt(self.worker(step, phase, drop))
                cut = self.receipt(self.worker(step, phase, drop, extra=f"Cut: {step} | {HUMAN} | {SOURCE}\n"))
                self.assertEqual((cut.returncode, cut.stderr), (plain.returncode, plain.stderr))
                self.assertEqual(plain.returncode, 1 if drop else 0, plain.stderr)


class CutSourceReachTests(WorkerCutFixture):
    """Correction 27.2, rulings 3 and 4 (F30-3, F30-4): where a relative Cut source resolves, and one size limit for it."""
    LIMIT = 2 * 1024 * 1024

    def test_a_relative_source_resolves_from_the_folder_of_the_file_that_holds_the_cut(self):
        step, phase, drop = self.minima()[0]
        (self.f.root / "own.log").write_text(f"The user, 2026-10-17:\n{HUMAN}\n")
        state = self.parent_holding(f"Cut: grilling | {HUMAN} | only-here.log")
        bare = self.parent_holding("", name="parent-bare")
        for seam, check in self.seams():
            with self.subTest(seam):
                # its own Cut: the brief's folder; the parent State's copy of a Cut: the State's folder
                own = self.worker(step, phase, drop, extra=f"Cut: grilling | {HUMAN} | own.log\n")
                self.assertEqual(check(own).returncode, 0, check(own).stderr)
                under = check(self.worker(step, phase, drop, state=bare, extra=f"Cut: grilling | {HUMAN} | own.log\n"))
                self.assertEqual(under.returncode, 0, under.stderr)  # a State in another folder does not move it
                lost = check(self.worker(step, phase, drop, extra=f"Cut: grilling | {HUMAN} | only-here.log\n"))
                self.assertEqual(lost.returncode, 1, lost.stderr)
                self.assertIn(f"Cut source only-here.log is unavailable at {self.f.root}/only-here.log", lost.stderr)
                inherited = check(self.worker(step, phase, drop, state=state))
                self.assertEqual(inherited.returncode, 0, inherited.stderr)
                state.write_text(state.read_text().replace("only-here.log", "own.log"))
                wrong = check(self.worker(step, phase, drop, state=state))
                self.assertEqual(wrong.returncode, 1, wrong.stderr)
                self.assertIn(f"Cut source own.log is unavailable at {state.parent}/own.log", wrong.stderr)
                state.write_text(state.read_text().replace("own.log", "only-here.log"))

    def test_a_cut_source_over_the_size_limit_is_refused_the_same_way_at_every_seam(self):
        step, phase, drop = self.minima()[0]
        tail = f"\n{HUMAN}\n".encode()
        for size, refused in ((self.LIMIT, False), (self.LIMIT + 1, True)):
            (self.f.root / "session.jsonl").write_bytes(b"x" * (size - len(tail)) + tail)
            for seam, check in self.seams():
                with self.subTest(size=size, seam=seam):
                    result = check(self.worker(step, phase, drop, extra=f"Cut: grilling | {HUMAN} | session.jsonl\n"))
                    self.assertEqual(result.returncode, 1 if refused else 0, result.stderr)
                    if refused:
                        self.assertIn("Cut source session.jsonl is larger than 2097152 bytes", result.stderr)

class RequiredStepsInTheMapTests(MapFixture):
    def steps_line(self, prefix):
        lines = [l for l in (self.pool / MAP).read_text().splitlines() if l.startswith(prefix)]
        self.assertEqual(len(lines), 1, prefix)
        return lines[0]

    def test_the_shipped_map_lists_required_steps_for_each_route_and_branch(self):
        text = (self.pool / MAP).read_text()
        self.assertEqual(text.count("\n## Required steps\n"), 1)
        for prefix in ("- research:", "- plan:", "- build, multi-session yes:", "- build, multi-session no:",
                       "- debug:", "- review:"):
            self.steps_line(prefix)

    def test_the_map_states_the_rule_the_gates_enforce(self):
        text = (self.pool / MAP).read_text()
        self.assertNotIn("before the current phase", text)
        self.assertIn("words before the first colon", text)

    def test_a_map_without_required_steps_holds_the_gate(self):
        self.edit_map("\n## Required steps\n", "\n## Other steps\n")
        self.refused("Required steps")

    def test_a_repeated_section_holds_the_gate(self):
        map_file = self.pool / MAP
        map_file.write_text(map_file.read_text() + "\n## Required steps\n\n- build, multi-session no: scope\n")
        self.refused("'## Required steps' 2 times")

    def test_a_missing_route_or_branch_holds_the_gate(self):
        for prefix, name in (("- research:", "research"), ("- build, multi-session yes:", "multi-session yes")):
            with self.subTest(name):
                line = self.steps_line(prefix)
                self.edit_map(line + "\n", "")
                try:
                    self.refused("Required steps", name)
                finally:
                    self.edit_map("\n## Required steps\n", "\n## Required steps\n\n" + line + "\n")

    def test_a_malformed_or_repeated_step_line_holds_the_gate(self):
        line = self.steps_line("- plan:")
        for label, bad, needle in (("unknown route", "- sprint: scope, plan", "sprint"),
                                   ("placeholder step", "- plan: scope, <phase>", "step"),
                                   ("empty list", "- plan:", "plan"),
                                   ("repeated step", "- plan: scope, scope, plan", "repeats a step")):
            with self.subTest(label):
                self.edit_map(line, bad)
                try:
                    self.refused("Required steps", needle)
                finally:
                    self.edit_map(bad, line)

    def test_a_table_in_the_section_still_counts_as_a_fifth_table(self):
        self.edit_map("\n## Required steps\n", "\n## Required steps\n\n| a |\n|---|\n| b |\n")
        self.refused("tables")


if __name__ == "__main__":
    unittest.main()
