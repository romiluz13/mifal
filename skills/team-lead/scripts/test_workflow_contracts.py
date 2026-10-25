"""Exercise opt-in Matt checks through the public validator CLI."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("validate_contracts.py")
# The workflow map's required steps (ticket 04) read the Phase checklist: a record accepted or reviewed on any route
# must show that route's steps done. One checklist shows them all, so a fixture reaching a late gate need not
# be taught each route's steps.
STEPS_DONE = "".join(f"- [x] {name}: done\n" for name in (
    "Scope", "Inspect", "Source", "Investigate", "Synthesize", "Grilling", "Resolve", "Plan", "To-spec", "To-tickets",
    "Reproduce", "Hypothesis", "Diagnose", "Implement", "Review", "Substantiate", "Regression", "Verify", "Retro"))
STEPS_BEFORE_REVIEW = "".join(f"- [x] {name}: done\n" for name in (
    "Scope", "Inspect", "Grilling", "To-spec", "To-tickets", "Reproduce", "Hypothesis", "Diagnose", "Implement"))
IMPLEMENT_PENDING = "- [ ] Implement: behavior test must pass\n"
BEFORE_IMPLEMENT = "- [x] Scope: asked\n- [x] Grilling: accepted\n" + IMPLEMENT_PENDING


class WorkflowTests(unittest.TestCase):
    DECISIONS = "Use the existing interface and agreed checks."

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.record = self.root / "task.md"
        self.procedure = self.root / "custom" / "SKILL.md"
        self.procedure.parent.mkdir()
        self.procedure.write_text("A fixture procedure.\n")
        self.procedure_digest = hashlib.sha256(self.procedure.read_bytes()).hexdigest()
        pool = Path.home() / ".agents" / "skills"
        self.entry = (pool / "engineering-workflow" / "SKILL.md").resolve()
        self.entry_digest = hashlib.sha256(self.entry.read_bytes()).hexdigest()
        self.router = (pool / "ask-matt" / "SKILL.md").resolve()
        self.router_digest = hashlib.sha256(self.router.read_bytes()).hexdigest()
        self.phase_skills = [(pool / name / "SKILL.md").resolve()
                             for name in ("implement", "tdd", "code-review")]
        self.accepted_plan = self.root / "accepted-plan.md"
        self.accepted_plan.write_text(self.plan_text(griller=self.pin(self.griller_task())))
        self.grilling = ("Grilling: accepted: sha256:" +
                         hashlib.sha256(self.accepted_plan.read_bytes()).hexdigest() +
                         f" | {self.accepted_plan}\n")
        self.retro_report = self.root / "retro.md"
        self.retro_report.write_text("## Sources\nCurrent fixture session and checked workflow.\n"
                                    "## Findings\nNo additional environment change is justified by this fixture.\n")
        self.retro = ("Retro: sha256:" + hashlib.sha256(self.retro_report.read_bytes()).hexdigest() +
                      f" | {self.retro_report}\nCheck: retro | passed | current fixture session reviewed\n")
        self.closing_skills = [(pool / name / "SKILL.md").resolve()
                               for name in ("retro", "writing-for-agents")]


    default_decision = "multi-session: no; reason: the fixture is one slice in one session"

    def run_check(self, kind, text, *args):
        self.record.write_text(text)
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), kind, str(self.record), *args],
            capture_output=True, text=True,
        )

    def brief(self):
        return ("---\ntask: 1\nowner: worker\nlatitude: look\n"
                "return: task.md\n---\n# Task 1\n## Why\nInspect a change.\n"
                "## Outcome\nEvidence-backed review.\n## Done means\n"
                "- behavior: check the artifact.\n## Stop rule\nOne pass.\n")

    def workflow(self):
        return ("\n## Workflow\nMethodology: matt\nExecutor: worker\nRoute: build\nPhase: implement\n"
                "Next gate: test the changed behavior\nStart: sha256:" + "a" * 64 + "\n"
                f"Route decision: {self.default_decision}\n"
                "DDD: n/a: no unfamiliar API assumption\nUX: n/a: no journey change\n" + self.grilling + self.retro +
                f"Procedure: {self.procedure}\n"
                f"Procedure: {self.router}\n"
                f"Procedure: {self.entry}\n" + "".join(f"Procedure: {p}\n" for p in self.phase_skills + self.closing_skills) + self.load_lines() +
                "\n## Phase checklist\n- [x] Context: sources inspected\n" + BEFORE_IMPLEMENT)

    def load_lines(self, executor="worker"):
        return (f"Loaded: {self.router} | {executor}: sha256:{self.router_digest} read event fixture-router before work\n"
                f"Loaded: {self.procedure} | {executor}: sha256:{self.procedure_digest} read event fixture-1 before work\n"
                f"Loaded: {self.entry} | {executor}: sha256:{self.entry_digest} read event fixture-2 before work\n" +
                "".join(f"Loaded: {p} | {executor}: sha256:{hashlib.sha256(p.read_bytes()).hexdigest()} read event fixture-phase before work\n" for p in self.phase_skills + self.closing_skills))

    def plan_text(self, scope='Accepted: "user-approved fixture ticket" | decisions.md#fixture',
                  decisions=DECISIONS, griller=None):
        """Grilling evidence; `griller` is the pin line a griller task earns, None for a plan only the lead wrote."""
        named = f"Griller: {griller}\n" if griller else ""
        return (f"## Accepted scope\n{scope}\nInspect and implement the agreed behavior.\n"
                f"## Design decisions\n{named}{decisions}\n")

    def accept_with(self, plan):
        """Make `plan` the shared record's Grilling evidence; returns the record text."""
        self.accepted_plan.write_text(plan)
        self.grilling = ("Grilling: accepted: sha256:" + hashlib.sha256(self.accepted_plan.read_bytes()).hexdigest() +
                         f" | {self.accepted_plan}\n")
        return self.workflow()

    def design_hash(self, decisions):
        """What a griller records: sha256 of the design heading and its decision lines, without Griller: lines."""
        return hashlib.sha256(f"## Design decisions\n{decisions}\n".encode()).hexdigest()

    def griller_task(self, owner="griller", name="griller.md", frontier="Frontier: empty", skills=("grilling",),
                     closes="Closes: 2", decisions=None, plan=None, binding=None,
                     claims="- findings: passed (frontier recomputed after the last answer)\n"):
        """A closed griller task: brief, Workflow record and a latest return that passes `receipt --matt`.
        `binding` replaces the lines that name the plan grilled and its design digest (`decisions`, `plan`)."""
        if binding is None:
            binding = (f"Plan path: {plan or self.accepted_plan}\n"
                       f"Design digest: sha256:{self.design_hash(decisions or self.DECISIONS)}\n")
        pool = Path.home() / ".agents" / "skills"
        bodies = [self.entry, self.router] + [(pool / name_ / "SKILL.md").resolve() for name_ in skills]
        path = self.root / name
        path.write_text(
            f"---\ntask: 2\nowner: {owner}\nlatitude: look\nreturn: {name}\n---\n# Grill the plan\n"
            "## Why\nThe lead's plan needs an independent interview.\n## Outcome\nA plan grilled to an empty frontier.\n"
            "## Done means\n- findings: the plan grilled to an empty frontier\n## Stop rule\nOne pass.\n"
            f"\n## Workflow\nMethodology: matt\nExecutor: {owner}\nRoute: research\nPhase: investigate\n"
            "Next gate: frontier empty\nStart: sha256:" + "c" * 64 + "\nDDD: n/a: no unfamiliar API\n"
            "UX: n/a: no journey change\n" + "".join(f"Procedure: {b}\n" for b in bodies) +
            "\n## Phase checklist\n- [x] Scope: plan read\n- [ ] Investigate: rounds pending\n"
            f"\n## Return\n{closes}\n### Result\nGrilled the plan.\n" + binding + (frontier + "\n" if frontier else "") +
            "### Claims\n" + claims + "### Evidence\n" +
            "".join(f"Loaded: {b} | {owner}: sha256:{hashlib.sha256(b.read_bytes()).hexdigest()} "
                    "read event griller-1 before work\n" for b in bodies))
        return path

    def pin(self, path):
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() + f" | {path}"

    def test_griller_pointer_is_a_pinned_readable_task_file(self):
        griller = self.griller_task()
        for label, line, expected in (
                ("unpinned path", str(griller), "Griller needs 'sha256:<digest> | <griller task file>'"),
                ("missing file", f"sha256:{'0' * 64} | {self.root / 'absent.md'}", "unavailable"),
                ("wrong digest", f"sha256:{'0' * 64} | {griller}", "changed since the evidence pinned it")):
            with self.subTest(label):
                result = self.run_check("workflow", self.accept_with(self.plan_text(griller=line)), "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(expected, result.stderr)
        pinned = self.pin(griller)
        griller.write_text(griller.read_text() + "\nA late edit after the plan pinned this file.\n")
        late = self.run_check("workflow", self.accept_with(self.plan_text(griller=pinned)), "--gate", "entry")
        self.assertEqual(late.returncode, 1, late.stderr)
        self.assertIn("changed since the evidence pinned it", late.stderr)

    def refuse_griller(self, griller, *expected):
        """Name `griller` in the shared record; the entry gate must exit 1 and say each of `expected`."""
        result = self.run_check("workflow", self.accept_with(self.plan_text(griller=self.pin(griller))),
                                "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        for text in expected:
            self.assertIn(text, result.stderr)

    def test_griller_receipt_must_validate(self):
        stale = self.griller_task(name="stale.md")
        stale.write_text(stale.read_text().replace(self.entry_digest, "0" * 64))
        for label, griller, underlying in (
                ("no Closes line", self.griller_task(closes=""), "missing 'Closes: <id>'"),
                ("stale read record", stale, "Loaded body changed")):
            with self.subTest(label):
                self.refuse_griller(griller, "receipt does not validate", underlying)

    def test_closed_receipts_are_not_regated_but_reused_evidence_meets_the_current_gate(self):
        accepted_by_the_lead = self.accept_with(self.plan_text(scope="Accepted: user-approved fixture ticket"))
        receipt = ("\n## Return\nCloses: 1\n### Result\nReviewed fixture.\n### Claims\n"
                   "- behavior: passed at the fixture digest\n### Evidence\nReview trace.\n" + self.load_lines())
        closed = self.run_check("receipt", self.brief() + accepted_by_the_lead + receipt, "--matt")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        for kind, record, args in (("brief", self.brief() + accepted_by_the_lead, ("--matt",)),
                                   ("workflow", accepted_by_the_lead, ("--gate", "entry"))):
            with self.subTest(kind=kind):
                reused = self.run_check(kind, record, *args)
                self.assertEqual(reused.returncode, 1, reused.stderr)
                self.assertIn("needs a Griller:", reused.stderr)
                self.assertIn("needs the human's quote and a source pointer", reused.stderr)

    def test_no_version_or_legacy_key_opts_out_of_the_griller(self):
        lead_only = self.accept_with(self.plan_text())
        for key in ("Version: 1", "Legacy: true", "Grilling version: legacy", "Rules: previous"):
            with self.subTest(key=key):
                result = self.run_check("workflow", lead_only.replace("Phase: implement", f"Phase: implement\n{key}"),
                                        "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("unknown Workflow field", result.stderr)
        declared = self.accept_with(self.plan_text(decisions="Version: 1\nLegacy: yes\nGriller: not needed"))
        result = self.run_check("workflow", declared, "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Griller needs 'sha256:<digest> | <griller task file>'", result.stderr)

    def test_the_human_quote_needs_a_source_pointer(self):
        griller = self.pin(self.griller_task())
        for scope in ('Accepted: "user-approved fixture ticket"', 'Accepted: "user-approved fixture ticket" |',
                      'Accepted: "user-approved fixture ticket" | pending', 'Accepted: | decisions.md#fixture'):
            with self.subTest(scope=scope):
                result = self.run_check("workflow", self.accept_with(self.plan_text(scope=scope, griller=griller)),
                                        "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("needs the human's quote and a source pointer", result.stderr)

    def test_the_human_quote_covers_scope_only(self):
        quoted = self.plan_text(griller=self.pin(self.griller_task()),
                                decisions='Accepted: "use the new interface" | decisions.md#design')
        result = self.run_check("workflow", self.accept_with(quoted), "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("the human's quote covers scope only", result.stderr)

    def test_griller_must_return_an_empty_frontier(self):
        twice = self.griller_task(name="twice.md", frontier="Frontier: empty\nFrontier: empty")
        for label, griller, found in (
                ("no frontier line", self.griller_task(name="none.md", frontier=""), "found none"),
                ("open questions", self.griller_task(name="open.md", frontier="Frontier: 2 open (Q3, Q4)"),
                 "found 'Frontier: 2 open (Q3, Q4)'"),
                ("fenced example only", self.griller_task(name="fenced.md", frontier="```\nFrontier: empty\n```"),
                 "found none"),
                ("said twice", twice, "found 2 lines")):
            with self.subTest(label):
                self.refuse_griller(griller, "does not return an empty frontier", found)

    def test_only_the_latest_return_states_the_frontier(self):
        def two_returns(first, latest):
            griller = self.griller_task(name="rounds.md", frontier=first)
            head, _, returned = griller.read_text().partition("\n## Return\n")
            griller.write_text(head + "\n## Return\n" + returned + "\n## Return\n" + returned.replace(first, latest))
            return griller
        self.refuse_griller(two_returns("Frontier: empty", "Frontier: 1 open (Q4)"),
                            "does not return an empty frontier", "found 'Frontier: 1 open (Q4)'")
        later = two_returns("Frontier: 3 open", "Frontier: empty")
        result = self.run_check("workflow", self.accept_with(self.plan_text(griller=self.pin(later))), "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_griller_needs_a_grilling_read_record(self):
        pool = Path.home() / ".agents" / "skills"
        unlisted = self.griller_task(name="unlisted.md", skills=())
        grilling = (pool / "grilling" / "SKILL.md").resolve()
        unlisted.write_text(unlisted.read_text() + f"Loaded: {grilling} | griller: sha256:"
                            f"{hashlib.sha256(grilling.read_bytes()).hexdigest()} read event griller-2 before work\n")
        for label, griller in (("no grilling body", self.griller_task(skills=())),
                               ("only the wrapper", self.griller_task(name="wrapper.md", skills=("grill-with-docs",))),
                               ("loaded but not listed", unlisted)):
            with self.subTest(label):
                self.refuse_griller(griller, "has no grilling read record")

    def test_griller_cannot_be_the_executor_it_grills(self):
        for owner in ("worker", "Worker"):
            with self.subTest(owner=owner):
                self.refuse_griller(self.griller_task(owner=owner), "the same agent as the record's Executor")

    def test_griller_cannot_be_the_parent_that_dispatched_the_work(self):
        parent = self.root / "parent.md"
        parent.write_text("## Workflow\nMethodology: matt\nExecutor: lead\nRoute: build\nPhase: implement\n"
                          "\n## Phase checklist\n- [x] Context: sources inspected\n- [ ] Implement: pending\n")
        lead_griller = self.griller_task(owner="lead")
        text = self.accept_with(self.plan_text(griller=self.pin(lead_griller))).replace(
            "Phase: implement", f"Phase: implement\nState: {parent}", 1)
        result = self.run_check("brief", self.brief() + text, "--matt")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("the same agent as the parent's Executor", result.stderr)
        other = self.accept_with(self.plan_text(griller=self.pin(self.griller_task()))).replace(
            "Phase: implement", f"Phase: implement\nState: {parent}", 1)
        passed = self.run_check("brief", self.brief() + other, "--matt")
        self.assertEqual(passed.returncode, 0, passed.stderr)

    def test_a_parent_whose_executor_cannot_be_read_fails_closed(self):
        checklist = "\n## Phase checklist\n- [x] Context: sources inspected\n- [ ] Implement: pending\n"
        parent = self.root / "parent.md"
        for label, state in (
                ("bold field", "## Workflow\n**Executor:** lead\n" + checklist),
                ("variant heading", "## Workflow record\nExecutor: lead\n" + checklist),
                ("frontmatter only", "---\ntask: 0\nowner: lead\nlatitude: own\nreturn: state.md\n---\n" + checklist),
                ("no Executor at all", "## Workflow\nMethodology: matt\n" + checklist),
                ("empty Executor", "## Workflow\nExecutor:\n" + checklist),
                ("file missing", None)):
            for owner in ("lead", "griller"):
                with self.subTest(label, owner=owner):
                    parent.unlink(missing_ok=True)
                    if state is not None:
                        parent.write_text(state)
                    text = self.accept_with(self.plan_text(griller=self.pin(self.griller_task(owner=owner)))).replace(
                        "Phase: implement", f"Phase: implement\nState: {parent}", 1)
                    result = self.run_check("brief", self.brief() + text, "--matt")
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("cannot determine the parent's Executor", result.stderr)
        no_state = self.run_check("brief", self.brief() + self.workflow(), "--matt")
        self.assertEqual(no_state.returncode, 0, no_state.stderr)

    def design_digest(self, plan_text):
        plan = self.root / "digest-plan.md"
        plan.write_bytes(plan_text.encode("utf-8"))
        return subprocess.run([sys.executable, "-B", str(SCRIPT), "design-digest", str(plan)],
                              capture_output=True, text=True)

    def test_design_digest_hashes_the_design_decisions_without_the_griller_lines(self):
        plan = ('## Accepted scope\nAccepted: "go" | chat.md\nScope prose.\n'
                f"## Design decisions\nGriller: sha256:{'a' * 64} | g.md\nUse the existing interface.\n\nSecond line.  \n"
                "## Notes\nOther.\n")
        # worked example: printf '## Design decisions\nUse the existing interface.\n\nSecond line.\n' | shasum -a 256
        literal = "sha256:49830085e74e55ed5aa711439b9d0ec30614b8633a7d65b8ee4bc912f2547f76"
        result = self.design_digest(plan)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, literal), result.stderr)
        same = {
            "scope edited": plan.replace("Scope prose.", "A different scope entirely."),
            "notes edited": plan.replace("Other.", "Other, and more."),
            "griller lines changed or added": plan.replace(f"Griller: sha256:{'a' * 64} | g.md\n",
                                                           f"Griller: sha256:{'b' * 64} | h.md\nGriller:\nGriller: x\n"),
            "CRLF line endings": plan.replace("\n", "\r\n"),
            "trailing whitespace": plan.replace("Use the existing interface.", "Use the existing interface. \t"),
            "blank lines closing the section": plan.replace("## Notes", "\n\n## Notes"),
        }
        for label, text in same.items():
            with self.subTest(label):
                again = self.design_digest(text)
                self.assertEqual((again.returncode, again.stdout.strip()), (0, literal), again.stderr)
        fenced = plan.replace("Second line.", "```\n## Not a heading\nGriller: kept\n```\nSecond line.")
        changed = {
            "design line edited": plan.replace("existing", "hosted"),
            "design line added": plan.replace("Second line.", "Second line.\nThird line."),
            "interior blank line removed": plan.replace("interface.\n\n", "interface.\n"),
            "heading renamed": plan.replace("## Design decisions", "## Design decisions (v2)"),
            "a sibling design section": plan + "## Design decisions addendum\nReplace the validator.\n",
            "fenced content (heading and Griller-looking line inside a fence stay)": fenced,
            "fenced content edited": fenced.replace("kept", "edited"),
            "a griller-looking list item": plan.replace("Second line.", "- Griller: not a griller line\nSecond line."),
        }
        seen = {literal}
        for label, text in changed.items():
            with self.subTest(label):
                other = self.design_digest(text)
                self.assertEqual(other.returncode, 0, other.stderr)
                self.assertRegex(other.stdout.strip(), r"^sha256:[0-9a-f]{64}$")
                self.assertNotIn(other.stdout.strip(), seen)
                seen.add(other.stdout.strip())

    def test_the_griller_must_have_grilled_these_design_decisions(self):
        pinned = self.pin(self.griller_task())
        smuggled = "Replace the validator with a hosted service."
        for label, plan in (
                ("F1-plan-edited-after-griller-closed",
                 self.plan_text(griller=pinned, decisions=f"{self.DECISIONS}\nNEW after the griller closed: {smuggled}")),
                ("design added in a sibling section",
                 self.plan_text(griller=pinned) + f"## Design decisions addendum\n{smuggled}\n")):
            with self.subTest(label):
                result = self.run_check("workflow", self.accept_with(plan), "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("the griller did not grill these design decisions", result.stderr)
        unrelated = self.griller_task(name="newsletter.md", plan=self.root / "newsletter-plan.md",
                                      decisions="Redesign the newsletter header.")
        with self.subTest("F1-griller-of-an-unrelated-plan"):
            self.refuse_griller(unrelated, "the griller did not grill these design decisions", "names plan")
        with self.subTest("scope edits need no new griller"):
            scope = self.plan_text(scope='Accepted: "a different scope, same design" | chat.md#later', griller=pinned)
            result = self.run_check("workflow", self.accept_with(scope), "--gate", "entry")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_griller_return_must_name_the_plan_and_carry_its_design_digest(self):
        digest = f"Design digest: sha256:{self.design_hash(self.DECISIONS)}\n"
        plan = f"Plan path: {self.accepted_plan}\n"
        for label, binding, expected in (
                ("neither line", "", "needs exactly one 'Design digest:"),
                ("no plan path", digest, "needs exactly one 'Plan path:"),
                ("no digest", plan, "needs exactly one 'Design digest:"),
                ("digest said twice", plan + digest + digest, "needs exactly one 'Design digest:"),
                ("plan path said twice", plan + plan + digest, "needs exactly one 'Plan path:"),
                ("malformed digest", plan + "Design digest: sha256:123\n", "needs exactly one 'Design digest:"),
                ("blank plan path", "Plan path:\n" + digest, "needs exactly one 'Plan path:"),
                ("fenced example only", plan + "```\n" + digest + "```\n", "needs exactly one 'Design digest:"),
                ("inside an HTML comment", plan + "<!--\n" + digest + "-->\n", "needs exactly one 'Design digest:"),
                ("inside an unclosed HTML comment", plan + "<!--\n" + digest, "needs exactly one 'Design digest:")):
            with self.subTest(label):
                self.refuse_griller(self.griller_task(name="bound.md", binding=binding), expected)

    def test_the_named_plan_is_compared_as_a_file_not_as_text(self):
        alias = self.root / "alias-plan.md"
        alias.symlink_to(self.accepted_plan)
        for label, named in (("symlink to the plan", alias), ("relative to the griller", "accepted-plan.md"),
                             ("with a dot-dot", self.root / "custom" / ".." / "accepted-plan.md")):
            with self.subTest(label):
                griller = self.griller_task(plan=named)
                result = self.run_check("workflow", self.accept_with(self.plan_text(griller=self.pin(griller))),
                                        "--gate", "entry")
                self.assertEqual(result.returncode, 0, result.stderr)
        for label, named in (("a copy with the same text", "copy-of-plan.md"), ("a missing file", "absent-plan.md")):
            with self.subTest(label):
                text = self.accept_with(self.plan_text(griller=self.pin(self.griller_task(plan=named))))
                (self.root / "copy-of-plan.md").write_bytes(self.accepted_plan.read_bytes())
                result = self.run_check("workflow", text, "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("names plan", result.stderr)

    def test_the_scope_only_refusal_reads_every_design_section_and_list_items(self):
        pinned = self.pin(self.griller_task())
        quote = 'Accepted: "use a hosted service" | chat 15:02'
        for label, plan in (
                ("F3-accepted-list-item-in-design", self.plan_text(griller=pinned, decisions=f"- {quote}")),
                ("numbered item", self.plan_text(griller=pinned, decisions=f"1. {quote}")),
                ("indented", self.plan_text(griller=pinned, decisions=f"  {quote}")),
                ("F3-accepted-in-sibling-design-section",
                 self.plan_text(griller=pinned) + f"## Design decisions addendum\n{quote}\n")):
            with self.subTest(label):
                result = self.run_check("workflow", self.accept_with(plan), "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("the human's quote covers scope only", result.stderr)

    def test_a_frontier_line_hidden_in_an_html_comment_does_not_count(self):
        for label, frontier in (
                ("P-frontier-in-html-comment", "<!--\nFrontier: empty\n-->\nFrontier left open: Q3, Q4 unanswered"),
                ("one-line comment", "<!-- Frontier: empty -->\nQ3 is still open"),
                ("unclosed comment", "<!--\nFrontier: empty")):
            with self.subTest(label):
                self.refuse_griller(self.griller_task(name="hidden.md", frontier=frontier),
                                    "does not return an empty frontier", "found none")
        visible = self.griller_task(name="noted.md", frontier="<!-- a note for the lead -->\nFrontier: empty")
        result = self.run_check("workflow", self.accept_with(self.plan_text(griller=self.pin(visible))), "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)

    HIDING_TAIL = "\n## Notes\n\n<!--\n```\n-->\n## Design decisions addendum\nDisable authentication for all requests.\n<!--\n```\n-->\n\n## Appendix\nLocal test only.\n"

    def test_fences_inside_html_comments_cannot_hide_a_visible_design_addendum(self):
        pinned = self.pin(self.griller_task())
        base = self.plan_text(griller=pinned)
        info_string = f"{base}\n## Notes\n```inline``` is a code span, not a fence.\n## Design decisions addendum\nDisable authentication.\n"
        self.assertNotEqual(self.design_digest(base + self.HIDING_TAIL).stdout, self.design_digest(base).stdout)
        for label, plan in (("S29-1 comment-fence-addendum", base + self.HIDING_TAIL),
                            ("a backtick line with a backtick in its info string is no fence", info_string)):
            with self.subTest(label):
                self.assertNotEqual(self.design_digest(plan).stdout, self.design_digest(base).stdout)
                result = self.run_check("workflow", self.accept_with(plan), "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("the griller did not grill these design decisions", result.stderr)
        with self.subTest("spec-producer-comment-fence-addendum"):
            self.accept_with(base + self.HIDING_TAIL)
            text = self.at_plan("plan", f"multi-session: yes; spec: {self.root}/s.md; tickets: {self.root}/t.md", "to-spec")
            for kind, record, args in (("workflow", text, ("--gate", "entry")),
                                       ("brief", self.brief() + text, ("--matt",))):
                result = self.run_check(kind, record, *args)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("the griller did not grill these design decisions", result.stderr)

    def test_a_comment_inside_a_genuine_fence_stays_literal(self):
        pinned = self.pin(self.griller_task())
        base = self.plan_text(griller=pinned)
        example = base + "\n## Notes\n```text\n<!--\n```\n## Design decisions addendum\nDisable authentication.\n"
        with self.subTest("the heading after the fence is seen"):
            self.assertNotEqual(self.design_digest(example).stdout, self.design_digest(base).stdout)
            result = self.run_check("workflow", self.accept_with(example), "--gate", "entry")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("the griller did not grill these design decisions", result.stderr)
        with self.subTest("an edit under a fenced example's heading is not design"):
            fenced = base + "\n## Notes\n```text\n<!--\n## Design decisions\nInside the example.\n```\n"
            edited = fenced.replace("Inside the example.", "Edited inside the example.")
            self.assertEqual(self.design_digest(fenced).stdout, self.design_digest(edited).stdout)
        with self.subTest("the frontier after a fenced comment opener is read"):
            griller = self.griller_task(name="literal.md", frontier="```\n<!--\n```\nFrontier: empty")
            result = self.run_check("workflow", self.accept_with(self.plan_text(griller=self.pin(griller))), "--gate", "entry")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_design_heading_or_griller_line_inside_a_comment_is_not_visible(self):
        pinned = self.pin(self.griller_task())
        with self.subTest("a design section that exists only inside a comment is no section"):
            commented = (f"## Accepted scope\nAccepted: \"go\" | chat.md#1\nScope prose.\n<!--\n## Design decisions\n"
                         f"Griller: {pinned}\n{self.DECISIONS}\n-->\n")
            result = self.run_check("workflow", self.accept_with(commented), "--gate", "entry")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("needs one nonempty '## Design decisions' section", result.stderr)
        with self.subTest("a Griller: line inside a comment stays in the digest"):
            base = self.plan_text(griller=pinned)
            noted = base.replace(f"{self.DECISIONS}\n", f"{self.DECISIONS}\n<!--\nGriller: not a pin\n-->\n")
            edited = noted.replace("not a pin", "still not a pin")
            digests = {self.design_digest(t).stdout for t in (base, noted, edited)}
            self.assertEqual(len(digests), 3)

    def test_fences_and_comments_cannot_hide_a_nonempty_frontier(self):
        for label, frontier, found in (
                ("S29-1 comment-fence-frontier",
                 "Frontier: empty\n<!--\n```\n-->\nFrontier: 2 open (Q9, Q10)\n<!--\n```\n-->", "found 2 lines"),
                ("<!--> is a whole comment (CommonMark 0.31)", "Frontier: empty\n<!-->\nFrontier: 2 open (Q9)", "found 2 lines"),
                ("<!---> is a whole comment", "Frontier: empty\n<!--->\nFrontier: 2 open (Q9)", "found 2 lines"),
                ("a code span is not a comment", "Frontier: empty\nThe `<!--` marker opens comments.\nFrontier: 2 open (Q9)", "found 2 lines"),
                ("a backtick in the info string is no fence", "Frontier: empty\n```a``` text\nFrontier: 2 open (Q9)", "found 2 lines")):
            with self.subTest(label):
                self.refuse_griller(self.griller_task(name="hid.md", frontier=frontier),
                                    "does not return an empty frontier", found)

    def test_an_unclosed_comment_or_fence_in_the_decisions_or_the_return_is_refused(self):
        ambiguous = "unclosed comment or fence in"
        for label, tail in (("unclosed comment", "<!--\nNever closed."), ("unclosed fence", "```text\nNever closed."),
                            ("unclosed tilde fence", "~~~\nNever closed.")):
            with self.subTest("design " + label):
                decisions = f"{self.DECISIONS}\n{tail}"
                griller = self.griller_task(name="bound-to-ambiguous.md", decisions=decisions)
                plan = self.plan_text(griller=self.pin(griller), decisions=decisions)
                result = self.run_check("workflow", self.accept_with(plan), "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(ambiguous + f" {self.accepted_plan}", result.stderr)
                cli = self.design_digest(plan)
                self.assertEqual(cli.returncode, 1, cli.stderr)
                self.assertIn(ambiguous, cli.stderr)
            with self.subTest("griller return " + label):
                griller = self.griller_task(name="ambiguous.md", frontier=f"Frontier: empty\n{tail}")
                self.refuse_griller(griller, ambiguous + f" {griller}")
        with self.subTest("closed constructs and an unclosed fence outside the decisions are fine"):
            base = self.plan_text(griller=self.pin(self.griller_task()))
            after = base + "\n## Notes\n```text\nan example nobody closed\n"
            result = self.run_check("workflow", self.accept_with(after), "--gate", "entry")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.design_digest(after).returncode, 0)

    def test_a_griller_that_reports_a_failed_or_untested_claim_does_not_count(self):
        for status in ("failed", "untested"):
            with self.subTest(status):
                griller = self.griller_task(name=f"{status}.md", claims=f"- findings: {status} (frontier not recomputed)\n")
                self.refuse_griller(griller, "the griller's return reports a failed or untested claim",
                                    f"findings: {status}")

    def test_design_digest_refuses_a_plan_without_design_decisions(self):
        for label, text in (("no section", "## Accepted scope\nAccepted: \"go\" | chat.md\nScope.\n"),
                            ("only inside a fence", "```\n## Design decisions\nUse a thing.\n```\n")):
            with self.subTest(label):
                result = self.design_digest(text)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("no '## Design decisions' section", result.stderr)
        missing = subprocess.run([sys.executable, "-B", str(SCRIPT), "design-digest", str(self.root / "absent.md")],
                                 capture_output=True, text=True)
        self.assertEqual(missing.returncode, 2, missing.stderr)

    def test_an_empty_griller_line_names_no_griller(self):
        plan = self.plan_text().replace("## Design decisions\n", "## Design decisions\nGriller:\n")
        self.assertIn("Griller:\nUse the existing interface", plan)
        result = self.run_check("workflow", self.accept_with(plan), "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("needs a Griller:", result.stderr)

    def test_a_plan_only_the_lead_wrote_names_no_griller(self):
        text = self.accept_with(self.plan_text())
        _, snapshot = self.artifact_snapshot()
        reviewed = text.replace("\n## Phase checklist", "\n" + snapshot + "\n## Phase checklist")
        finished = (self.brief() + text).replace(IMPLEMENT_PENDING, STEPS_DONE).replace(
            "\n## Phase checklist", "\n" + snapshot + "Check: behavior | passed | test trace at reviewed identity\n"
            "\n## Phase checklist") + "- [ ] Report\n"
        for kind, record, args in (("workflow", text, ("--gate", "entry")),
                                   ("brief", self.brief() + text, ("--matt",)),
                                   ("workflow", reviewed, ("--gate", "review")),
                                   ("workflow", finished, ("--gate", "accept"))):
            with self.subTest(kind=kind, args=args):
                result = self.run_check(kind, record, *args)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("needs a Griller:", result.stderr)

    def test_one_passing_griller_is_enough(self):
        weak = self.griller_task(name="weak.md", owner="worker")
        sound = self.griller_task(name="sound.md")
        both = self.plan_text(griller=self.pin(weak)).replace("Griller: ", f"Griller: {self.pin(sound)}\nGriller: ", 1)
        result = self.run_check("workflow", self.accept_with(both), "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)
        none_pass = self.run_check("workflow", self.accept_with(self.plan_text(griller=self.pin(weak))), "--gate", "entry")
        self.assertEqual(none_pass.returncode, 1, none_pass.stderr)

    def test_a_relative_griller_pointer_reads_from_the_evidence_not_the_record(self):
        (self.root / "plans").mkdir()
        evidence = self.root / "plans" / "plan.md"
        sound = self.griller_task(name="plans/sound.md", plan=evidence)
        evidence.write_text(self.plan_text(griller=f"sha256:{hashlib.sha256(sound.read_bytes()).hexdigest()} | sound.md"))
        pin = hashlib.sha256(evidence.read_bytes()).hexdigest()
        text = self.workflow().replace(self.grilling, f"Grilling: accepted: sha256:{pin} | {evidence}\n")
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)

    def with_skills(self, text, *names):
        """Select and load more canonical pool bodies for the record's phase."""
        pool = Path.home() / ".agents" / "skills"
        chosen = ""
        for name in names:
            body = (pool / name / "SKILL.md").resolve()
            chosen += (f"Procedure: {body}\nLoaded: {body} | worker: sha256:"
                       f"{hashlib.sha256(body.read_bytes()).hexdigest()} read event fixture-{name} before work\n")
        return text.replace("\n## Phase checklist", "\n" + chosen + "\n## Phase checklist", 1)

    def plan_record(self, phase="resolve", grilling=None):
        """The shared record on the plan route; `grilling` replaces the Grilling line ('' drops it)."""
        text = self.workflow().replace("Route: build", "Route: plan").replace("Phase: implement", f"Phase: {phase}")
        return text if grilling is None else text.replace(self.grilling, grilling)

    def test_a_plan_at_resolve_or_later_needs_a_grilling_line(self):
        for phase in ("resolve", "plan", "review", "verify", "deliver", "report"):
            with self.subTest(phase=phase):
                result = self.run_check("workflow", self.plan_record(phase, grilling=""), "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("plan record at resolve or later needs a Grilling line", result.stderr)

    def test_the_plan_grilling_rule_waits_for_resolve_and_spares_closed_receipts(self):
        for phase in ("scope", "inspect", "context", "research"):
            with self.subTest(phase=phase):
                result = self.run_check("workflow", self.plan_record(phase, grilling=""), "--gate", "entry")
                self.assertEqual(result.returncode, 0, result.stderr)
        late = self.plan_record("review", grilling="")
        receipt = ("\n## Return\nCloses: 1\n### Result\nReviewed fixture.\n### Claims\n"
                   "- behavior: passed at the fixture digest\n### Evidence\nReview trace.\n" + self.load_lines())
        closed = self.run_check("receipt", self.brief() + late + receipt, "--matt")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        for kind, record, args in (("brief", self.brief() + late, ("--matt",)),
                                   ("workflow", late, ("--gate", "entry"))):
            with self.subTest(kind=kind):
                result = self.run_check(kind, record, *args)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("needs a Grilling line", result.stderr)

    def test_a_plan_grills_in_the_open_but_cannot_be_delivered_unfinished(self):
        interview = "Grilling: interview: the design decisions are still open\n"
        open_plan = self.with_skills(self.plan_record("resolve", grilling=interview),
                                     "grill-with-docs", "grilling", "domain-modeling")
        result = self.run_check("workflow", open_plan, "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)
        for phase in ("review", "verify", "deliver", "report"):
            with self.subTest(phase=phase):
                unfinished = self.plan_record(phase, grilling=interview)
                result = self.run_check("workflow", unfinished, "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("Grilling interview is unfinished", result.stderr)

    def decide(self, text, decision):
        """Record Ask Matt's branch in the Workflow section."""
        return text.replace(f"Route decision: {self.default_decision}\n", "").replace(
            "\nDDD:", f"\nRoute decision: {decision}\nDDD:", 1)

    def test_a_single_session_decision_needs_a_reason(self):
        for label, decision in (("no reason clause", "multi-session: no"),
                                ("empty reason", "multi-session: no; reason:"),
                                ("placeholder reason", "multi-session: no; reason: TBD")):
            with self.subTest(label):
                result = self.run_check("workflow", self.decide(self.plan_record("plan"), decision), "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("'multi-session: no' needs a reason", result.stderr)
        stated = self.decide(self.plan_record("plan"), "multi-session: no; reason: one slice, one session, no schema change")
        result = self.run_check("workflow", stated, "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_single_session_reason_is_more_than_punctuation(self):
        for reason in ("-", ".", "--", "?!", "_", "* * *", "\u2014"):
            with self.subTest(reason=reason):
                decision = f"multi-session: no; reason: {reason}"
                result = self.run_check("workflow", self.decide(self.plan_record("plan"), decision), "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("'multi-session: no' needs a reason", result.stderr)
        for reason in ("- one slice, one session", "x", "\u4e00\u4e2a\u5207\u7247"):
            with self.subTest(reason=reason):
                decision = f"multi-session: no; reason: {reason}"
                result = self.run_check("workflow", self.decide(self.plan_record("plan"), decision), "--gate", "entry")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_route_decision_must_be_a_branch_ask_matt_names(self):
        for decision in ("maybe", "multi-session: sometimes", "single-session: yes"):
            with self.subTest(decision=decision):
                result = self.run_check("workflow", self.decide(self.plan_record("plan"), decision), "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("Route decision needs", result.stderr)

    def test_a_multi_session_decision_names_its_outputs(self):
        for label, decision in (("none named", "multi-session: yes"),
                                ("spec only", "multi-session: yes; spec: spec.md"),
                                ("tickets only", "multi-session: yes; tickets: issues.md"),
                                ("placeholder", "multi-session: yes; spec: <path>; tickets: issues.md"),
                                ("repeated", "multi-session: yes; spec: a.md; spec: b.md; tickets: issues.md"),
                                ("stray clause", "multi-session: yes; spec: spec.md; tickets: issues.md; extra: x")):
            with self.subTest(label):
                result = self.run_check("workflow", self.decide(self.plan_record("plan"), decision), "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("Route decision needs", result.stderr)

    def output(self, name):
        """A produced spec or tickets artifact; returns (path, the pin line a decision earns)."""
        path = self.root / name
        path.write_text(f"# {name}\nThe agreed work, sliced.\n")
        return path, f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()} | {path}"

    def test_implementation_is_refused_until_the_pinned_spec_and_tickets_exist(self):
        spec, pinned_spec = self.output("spec.md")
        tickets, pinned_tickets = self.output("tickets.md")
        gone = self.root / "gone.md"
        blank = self.root / "blank.md"
        blank.write_text("\n")
        pinned_blank = f"sha256:{hashlib.sha256(blank.read_bytes()).hexdigest()} | {blank}"
        for phase in ("implement", "implementation", "remediate", "review", "verify", "retro", "report"):
            for label, spec_ref, tickets_ref, expected in (
                    ("tickets pinned but blank", pinned_spec, pinned_blank, "the tickets are empty"),
                    ("both unpinned", spec, tickets, "the spec is unpinned"),
                    ("tickets unpinned", pinned_spec, tickets, "the tickets are unpinned"),
                    ("spec unpinned", spec, pinned_tickets, "the spec is unpinned"),
                    ("tickets named but not published", pinned_spec, self.root / "later.md", "the tickets are unpinned"),
                    ("spec pin to a missing file", f"sha256:{'0' * 64} | {gone}", pinned_tickets, "the spec is unavailable"),
                    ("wrong digest", f"sha256:{'0' * 64} | {spec}", pinned_tickets, "the spec changed since the decision pinned it")):
                with self.subTest(phase=phase, case=label):
                    text = self.decide(self.workflow().replace("Phase: implement", f"Phase: {phase}"),
                                       f"multi-session: yes; spec: {spec_ref}; tickets: {tickets_ref}")
                    result = self.run_check("workflow", text, "--gate", "entry")
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("holds implementation until the pinned spec and tickets exist", result.stderr)
                    self.assertIn(expected, result.stderr)
        ready = self.decide(self.workflow(), f"multi-session: yes; spec: {pinned_spec}; tickets: {pinned_tickets}")
        result = self.run_check("workflow", ready, "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)
        spec.write_text(spec.read_text() + "A late edit after the decision pinned the spec.\n")
        stale = self.run_check("workflow", ready, "--gate", "entry")
        self.assertEqual(stale.returncode, 1, stale.stderr)
        self.assertIn("the spec changed since the decision pinned it", stale.stderr)

    def at_plan(self, route, decision, *producers, grilling=None):
        """A record at the plan phase of `route`, with the producers it selects; `decision` None records no branch."""
        text = (self.plan_record("plan") if route == "plan"
                else self.workflow().replace("Phase: implement", "Phase: plan"))
        if grilling is not None:
            text = text.replace(self.grilling, grilling)
        return self.with_skills(text if decision is None else self.decide(text, decision), *producers)

    def test_the_spec_producer_is_allowed_once_grilling_is_complete_with_no_tickets_yet(self):
        later = self.root / "later"
        for route in ("plan", "build"):
            with self.subTest(route=route):
                text = self.at_plan(route, f"multi-session: yes; spec: {later}/spec.md; tickets: {later}/issues.md",
                                    "to-spec")
                for kind, record, args in (("workflow", text, ("--gate", "entry")),
                                           ("brief", self.brief() + text, ("--matt",))):
                    result = self.run_check(kind, record, *args)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_ticket_producer_is_allowed_once_the_spec_is_pinned_before_the_tickets_are_published(self):
        _, pinned_spec = self.output("spec.md")
        for route in ("plan", "build"):
            with self.subTest(route=route):
                text = self.at_plan(route, f"multi-session: yes; spec: {pinned_spec}; tickets: {self.root}/issues.md",
                                    "to-tickets")
                for kind, record, args in (("workflow", text, ("--gate", "entry")),
                                           ("brief", self.brief() + text, ("--matt",))):
                    result = self.run_check(kind, record, *args)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_producer_is_held_until_what_comes_before_it_is_ready(self):
        spec, pinned_spec = self.output("spec.md")
        interview = "Grilling: interview: the design decisions are still open\n"
        grill = ("grill-with-docs", "grilling", "domain-modeling")
        named = f"multi-session: yes; spec: {spec}; tickets: {self.root}/issues.md"
        for label, text, expected in (
                ("spec producer, grilling unfinished", self.at_plan("plan", named, "to-spec", *grill, grilling=interview),
                 "holds the spec producer (to-spec) until grilling is complete"),
                ("ticket producer, grilling unfinished",
                 self.at_plan("plan", f"multi-session: yes; spec: {pinned_spec}; tickets: {self.root}/issues.md",
                              "to-tickets", *grill, grilling=interview),
                 "holds the ticket producer (to-tickets) until grilling is complete"),
                ("ticket producer, spec unpinned", self.at_plan("plan", named, "to-tickets"),
                 "holds the ticket producer (to-tickets) until the pinned spec exists: the spec is unpinned"),
                ("ticket producer, spec pin changed",
                 self.at_plan("plan", f"multi-session: yes; spec: sha256:{'0' * 64} | {spec}; "
                              f"tickets: {self.root}/issues.md", "to-tickets"),
                 "the spec changed since the decision pinned it")):
            with self.subTest(label):
                result = self.run_check("workflow", text, "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(expected, result.stderr)

    def test_a_producer_needs_finished_grilling_whatever_the_decision_says(self):
        interview = "Grilling: interview: the design decisions are still open\n"
        grill = ("grill-with-docs", "grilling", "domain-modeling")
        _, pinned_spec = self.output("spec.md")
        stated = "multi-session: no; reason: one slice, one session, no schema change"
        for route in ("plan", "build"):
            for producer, spec_ref in (("to-spec", f"{self.root}/spec.md"), ("to-tickets", pinned_spec)):
                named = f"multi-session: yes; spec: {spec_ref}; tickets: {self.root}/issues.md"
                for label, decision in (("no decision", None), ("single session", stated), ("multi-session", named)):
                    with self.subTest(route=route, producer=producer, decision=label):
                        text = self.at_plan(route, decision, producer, *grill, grilling=interview)
                        result = self.run_check("workflow", text, "--gate", "entry")
                        self.assertEqual(result.returncode, 1, result.stderr)
                        self.assertIn("until grilling is complete", result.stderr)
        for route in ("plan", "build"):
            with self.subTest(finished=route):
                result = self.run_check("workflow", self.at_plan(route, None, "to-spec"), "--gate", "entry")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_ticket_producer_needs_a_pinned_spec_whatever_the_decision_says(self):
        stated = "multi-session: no; reason: one slice, one session, no schema change"
        for route in ("plan", "build"):
            for label, decision in (("no decision", None), ("single session", stated)):
                with self.subTest(route=route, decision=label):
                    text = self.at_plan(route, decision, "to-tickets")
                    result = self.run_check("workflow", text, "--gate", "entry")
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("selects the ticket producer (to-tickets), which is held until the pinned spec exists: "
                                  "the spec is not named", result.stderr)
                    self.assertNotIn("until grilling is complete", result.stderr)
        _, pinned_spec = self.output("spec.md")
        for route in ("plan", "build"):
            with self.subTest(named=route):
                named = f"multi-session: yes; spec: {pinned_spec}; tickets: {self.root}/issues.md"
                result = self.run_check("workflow", self.at_plan(route, named, "to-tickets"), "--gate", "entry")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_selecting_a_producer_does_not_lighten_the_hold_on_implementation(self):
        unpinned = f"multi-session: yes; spec: {self.root}/spec.md; tickets: {self.root}/issues.md"
        for producers in (("to-spec",), ("to-tickets",), ("to-spec", "to-tickets")):
            with self.subTest(producers=producers):
                text = self.with_skills(self.decide(self.workflow(), unpinned), *producers)
                result = self.run_check("workflow", text, "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("holds implementation until the pinned spec and tickets exist", result.stderr)
                self.assertIn("the spec is unpinned", result.stderr)
                self.assertIn("the tickets are unpinned", result.stderr)
        with self.subTest("late gate on an earlier phase"):
            held = self.decide(self.completed_workflow().replace("Phase: implement", "Phase: plan"), unpinned)
            result = self.run_check("workflow", self.with_skills(held, "to-spec"), "--gate", "review")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("holds implementation until the pinned spec and tickets exist", result.stderr)
        _, pinned_spec = self.output("spec.md")
        _, pinned_tickets = self.output("issues.md")
        ready = self.decide(self.workflow(), f"multi-session: yes; spec: {pinned_spec}; tickets: {pinned_tickets}")
        with self.subTest("both pinned"):
            result = self.run_check("workflow", self.with_skills(ready, "to-spec"), "--gate", "entry")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_producer_needs_finished_grilling_on_any_route(self):
        research = self.workflow().replace("Route: build", "Route: research").replace("Phase: implement", "Phase: scope")
        bare = research.replace(self.grilling, "")
        with self.subTest("no producer selected"):
            result = self.run_check("workflow", bare, "--gate", "entry")
            self.assertEqual(result.returncode, 0, result.stderr)
        with self.subTest("producer, no Grilling line"):
            result = self.run_check("workflow", self.with_skills(bare, "to-spec"), "--gate", "entry")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("until grilling is complete", result.stderr)
        with self.subTest("producer, accepted Grilling"):
            result = self.run_check("workflow", self.with_skills(research, "to-spec"), "--gate", "entry")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_producer_rules_spare_closed_receipts_and_the_build_route(self):
        pool = Path.home() / ".agents" / "skills"
        bodies = [(pool / name / "SKILL.md").resolve() for name in ("to-spec", "grill-with-docs", "grilling", "domain-modeling")]
        extra_loads = "".join(f"Loaded: {b} | worker: sha256:{hashlib.sha256(b.read_bytes()).hexdigest()} "
                              "read event fixture-extra before work\n" for b in bodies)
        interview = "Grilling: interview: the design decisions are still open\n"
        receipt = ("\n## Return\nCloses: 1\n### Result\nSpecified the fixture.\n### Claims\n"
                   "- behavior: passed at the fixture digest\n### Evidence\nSpec trace.\n" + self.load_lines() + extra_loads)
        for label, record in (("before resolve, no Grilling line",
                               self.with_skills(self.plan_record("inspect", grilling=""), "to-spec")),
                              ("unfinished interview, no branch",
                               self.at_plan("plan", None, "to-spec", "grill-with-docs", "grilling", "domain-modeling",
                                            grilling=interview))):
            with self.subTest(label):
                closed = self.run_check("receipt", self.brief() + record + receipt, "--matt")
                self.assertEqual(closed.returncode, 0, closed.stderr)
                for kind, text, args in (("brief", self.brief() + record, ("--matt",)),
                                         ("workflow", record, ("--gate", "entry"))):
                    result = self.run_check(kind, text, *args)
                    self.assertEqual(result.returncode, 1, f"{kind}: {result.stderr}")
        with self.subTest("the build route is not a plan record"):
            early = self.with_skills(self.workflow().replace("Phase: implement", "Phase: context"), "to-spec")
            result = self.run_check("workflow", early, "--gate", "entry")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_plan_under_review_does_not_need_the_spec_it_leads_to(self):
        named = f"multi-session: yes; spec: {self.root}/spec.md; tickets: {self.root}/issues.md"
        for phase in ("resolve", "review", "verify", "deliver", "report"):
            for gate in ("entry", "review", "accept"):
                with self.subTest(phase=phase, gate=gate):
                    text = self.decide(self.plan_record(phase), named)
                    result = self.run_check("workflow", text, "--gate", gate)
                    self.assertNotIn("route decision", result.stderr.lower())

    def test_a_single_session_decision_holds_no_implementation_and_leaves_a_producer_its_own_needs(self):
        stated = "multi-session: no; reason: one slice, one session, no schema change"
        for label, text in (("implementation", self.decide(self.workflow(), stated)),
                            ("spec producer", self.at_plan("plan", stated, "to-spec"))):
            with self.subTest(label):
                result = self.run_check("workflow", text, "--gate", "entry")
                self.assertEqual(result.returncode, 0, result.stderr)
        with self.subTest("ticket producer"):
            result = self.run_check("workflow", self.at_plan("build", stated, "to-tickets"), "--gate", "entry")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("which is held until the pinned spec exists", result.stderr)

    def test_a_plan_cannot_select_a_producer_before_resolve_whatever_the_decision_says(self):
        later = self.root / "later"
        stated = "multi-session: no; reason: one slice, one session, no schema change"
        named = f"multi-session: yes; spec: {later}/spec.md; tickets: {later}/issues.md"
        for phase in ("scope", "inspect", "context", "research"):
            for producer in ("to-spec", "to-tickets"):
                for grilling_label, grilling in (("no Grilling line", ""), ("accepted Grilling", None)):
                    for label, decision in (("no decision", None), ("single session", stated), ("multi-session", named)):
                        with self.subTest(phase=phase, producer=producer, grilling=grilling_label, decision=label):
                            record = self.plan_record(phase, grilling)
                            text = self.with_skills(record if decision is None else self.decide(record, decision), producer)
                            result = self.run_check("workflow", text, "--gate", "entry")
                            self.assertEqual(result.returncode, 1, result.stderr)
                            self.assertIn("a spec or ticket producer runs after resolve", result.stderr)

    def test_phase_prose_after_the_first_word_does_not_hide_a_producer(self):
        prose = self.plan_record("inspect", grilling="").replace(
            "Phase: inspect", "Phase: inspect, then resolve the design and plan")
        plain = self.run_check("workflow", prose, "--gate", "entry")
        self.assertEqual(plain.returncode, 0, plain.stderr)
        selected = self.run_check("workflow", self.with_skills(prose, "to-spec"), "--gate", "entry")
        self.assertEqual(selected.returncode, 1, selected.stderr)
        self.assertIn("a spec or ticket producer runs after resolve", selected.stderr)

    def test_route_decision_meets_every_gate_but_spares_closed_receipts(self):
        unpinned = f"multi-session: yes; spec: {self.root}/spec.md; tickets: {self.root}/issues.md"
        _, pinned_spec = self.output("spec.md")
        _, pinned_tickets = self.output("issues.md")
        pinned = f"multi-session: yes; spec: {pinned_spec}; tickets: {pinned_tickets}"
        receipt = ("\n## Return\nCloses: 1\n### Result\nBuilt the fixture.\n### Claims\n"
                   "- behavior: passed at the fixture digest\n### Evidence\nTest trace.\n" + self.load_lines())
        held = self.decide(self.completed_workflow(), unpinned)
        ready = self.decide(self.completed_workflow(), pinned)
        for kind, record, args in (("brief", self.brief() + self.decide(self.workflow(), unpinned), ("--matt",)),
                                   ("workflow", held, ("--gate", "review")),
                                   ("workflow", held, ("--gate", "accept"))):
            with self.subTest(kind=kind, args=args):
                result = self.run_check(kind, record, *args)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("holds implementation until the pinned spec and tickets exist", result.stderr)
        for gate in ("review", "accept"):
            with self.subTest(ready=gate):
                result = self.run_check("workflow", ready, "--gate", gate)
                self.assertEqual(result.returncode, 0, result.stderr)
            with self.subTest(late_gate_on_an_earlier_phase=gate):
                result = self.run_check("workflow", held.replace("Phase: implement", "Phase: plan"), "--gate", gate)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("holds implementation until the pinned spec and tickets exist", result.stderr)
        closed = self.run_check("receipt", self.brief() + self.decide(self.workflow(), unpinned) + receipt, "--matt")
        self.assertEqual(closed.returncode, 0, closed.stderr)

    def test_general_brief_keeps_its_existing_contract(self):
        result = self.run_check("brief", self.brief())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_matt_brief_refuses_missing_workflow_before_work(self):
        result = self.run_check("brief", self.brief(), "--matt")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Workflow", result.stderr)

    def test_behavioral_build_cannot_select_only_the_router(self):
        result = self.run_check("workflow", self.without_phase_skills(), "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("implement", result.stderr)
        self.assertIn("tdd", result.stderr)

    def without_phase_skills(self):
        return "\n".join(line for line in self.workflow().splitlines()
                         if not any(str(p) in line for p in self.phase_skills))

    def test_both_build_procedures_are_required(self):
        for missing in self.phase_skills[:2]:
            with self.subTest(missing=missing.parent.name):
                text = "\n".join(line for line in self.workflow().splitlines() if str(missing) not in line)
                result = self.run_check("workflow", text, "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(missing.parent.name, result.stderr)

    def test_docs_only_exception_is_explicit_and_does_not_force_tdd(self):
        for value, expected in (("n/a: docs-only: README wording only", 0),
                                ("n/a: because", 1), ("n/a: docs-only: TBD", 1)):
            with self.subTest(value=value):
                text = self.without_phase_skills().replace("Phase: implement", "Phase: implement\nImplement: " + value)
                result = self.run_check("workflow", text, "--gate", "entry")
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_coordination_exception_requires_the_lead_procedure(self):
        text = self.without_phase_skills().replace("Phase: implement", "Phase: implement\nImplement: n/a: coordination: workers own the behavioral code")
        refused = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(refused.returncode, 1, refused.stderr)
        self.assertIn("team-lead", refused.stderr)
        lead = Path.home() / ".agents/skills/team-lead/SKILL.md"
        loaded = f"Procedure: {lead}\nLoaded: {lead} | worker: sha256:{hashlib.sha256(lead.read_bytes()).hexdigest()} complete read event lead-before-dispatch\n"
        result = self.run_check("workflow", text.replace("\n## Phase checklist", "\n" + loaded + "\n## Phase checklist"), "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invented_phase_cannot_evade_the_procedure_minimum(self):
        result = self.run_check("workflow", self.without_phase_skills().replace("Phase: implement", "Phase: coding"), "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Phase must", result.stderr)

    def test_solo_note_uses_the_same_entry_check_without_a_brief(self):
        result = self.run_check("workflow", self.workflow(), "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_build_requires_evidence_before_skipping_the_interview(self):
        text = "\n".join(line for line in self.workflow().splitlines()
                         if not line.startswith("Grilling:"))
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Grilling needs 'interview: <reason>'", result.stderr)

    def test_grilling_evidence_must_include_accepted_scope_and_settled_design(self):
        for content, expected in (
            ("## Accepted scope\nAccepted: ticket1\n## Design decisions\nExisting seam.\n",
             "must describe the accepted work"),
            ("## Accepted scope\nAccepted: ticket1\nImplement feature.\n",
             "needs one nonempty '## Design decisions' section"),
            ("## Accepted scope\nAccepted: pending\nImplement feature.\n## Design decisions\nExisting seam.\n",
             "needs one Accepted: <actual approval"),
            ("## Accepted scope\nAccepted: ticket1\nImplement feature.\n## Design decisions\nTBD\n",
             "needs one nonempty '## Design decisions' section"),
            ("```md\n## Accepted scope\nAccepted: ticket1\nScope.\n## Design decisions\nSettled.\n```\n",
             "needs one nonempty '## Accepted scope' section"),
        ):
            with self.subTest(content=content):
                self.accepted_plan.write_text(content)
                pin = "sha256:" + hashlib.sha256(self.accepted_plan.read_bytes()).hexdigest()
                text = self.workflow().replace(self.grilling, f"Grilling: accepted: {pin} | {self.accepted_plan}\n")
                result = self.run_check("workflow", text, "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(expected, result.stderr)

    def test_changed_grilling_evidence_holds_dispatch(self):
        self.accepted_plan.write_text(self.accepted_plan.read_text() + "A new unresolved product decision.\n")
        result = self.run_check("brief", self.brief() + self.workflow(), "--matt")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Grilling evidence changed", result.stderr)

    def test_interview_mode_cannot_start_implementation(self):
        text = self.workflow().replace(self.grilling, "Grilling: interview: user decisions still open\n")
        result = self.run_check("brief", self.brief() + text, "--matt")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("unfinished", result.stderr)

    def test_planning_interview_loads_the_actual_provider_procedures(self):
        text = self.workflow().replace("Phase: implement", "Phase: plan").replace(
            self.grilling, "Grilling: interview: resolve design choices with the user\n")
        held = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(held.returncode, 1, held.stderr)
        pool = Path.home() / ".agents/skills"
        lines = ""
        for name in ("grill-with-docs", "grilling", "domain-modeling"):
            p = pool / name / "SKILL.md"
            lines += f"Procedure: {p}\nLoaded: {p} | worker: sha256:{hashlib.sha256(p.read_bytes()).hexdigest()} complete read event interview\n"
        prepared = self.run_check("workflow", text.replace("\n## Phase checklist", "\n" + lines + "\n## Phase checklist"), "--gate", "entry")
        self.assertEqual(prepared.returncode, 0, prepared.stderr)

    def test_retro_entry_can_start_before_the_report_exists(self):
        text = self.workflow().replace("Phase: implement", "Phase: retro").replace(self.retro, "")
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)
        for missing in self.closing_skills:
            with self.subTest(missing=missing.parent.name):
                unloaded = "\n".join(line for line in text.splitlines() if str(missing) not in line)
                result = self.run_check("workflow", unloaded, "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(missing.parent.name, result.stderr)
        completed = text.replace(IMPLEMENT_PENDING, STEPS_DONE)
        result = self.run_check("workflow", completed, "--gate", "accept")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Retro", result.stderr)

    def test_completed_build_cannot_omit_matts_retrospective(self):
        _, snapshot = self.artifact_snapshot()
        text = (self.brief() + self.workflow()).replace(IMPLEMENT_PENDING, STEPS_DONE).replace(
            "\n## Phase checklist", "\n" + snapshot + "Check: behavior | passed | reviewed fixture behavior\n\n## Phase checklist")
        text = "\n".join(line for line in text.splitlines() if not line.startswith("Retro:"))
        result = self.run_check("workflow", text, "--gate", "accept")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Retro", result.stderr)

    def completed_workflow(self):
        _, snapshot = self.artifact_snapshot()
        return (self.brief() + self.workflow()).replace(IMPLEMENT_PENDING, STEPS_DONE).replace(
            "\n## Phase checklist", "\n" + snapshot + "Check: behavior | passed | reviewed fixture behavior\n\n## Phase checklist")

    def test_retro_needs_current_report_and_actual_selected_body_reads(self):
        base = self.completed_workflow()
        for missing in self.closing_skills:
            with self.subTest(missing=missing):
                text = "\n".join(line for line in base.splitlines() if str(missing) not in line)
                result = self.run_check("workflow", text, "--gate", "accept")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(missing.parent.name, result.stderr)
        self.retro_report.write_text(self.retro_report.read_text() + "Changed finding.\n")
        result = self.run_check("workflow", base, "--gate", "accept")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Retro evidence changed", result.stderr)

    def test_retro_report_cannot_omit_sources_or_claim_completion_without_check(self):
        base = self.completed_workflow()
        text = "\n".join(line for line in base.splitlines() if not line.startswith("Check: retro"))
        result = self.run_check("workflow", text, "--gate", "accept")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("retro | passed", result.stderr)
        self.retro_report.write_text("## Findings\nNo new proposals.\n")
        pin = "sha256:" + hashlib.sha256(self.retro_report.read_bytes()).hexdigest()
        text = base.replace(self.retro, f"Retro: {pin} | {self.retro_report}\nCheck: retro | passed | reviewed\n")
        result = self.run_check("workflow", text, "--gate", "accept")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Sources", result.stderr)

    def test_debug_fix_requires_retro_but_diagnosis_only_can_close_honestly(self):
        base = self.completed_workflow().replace("Route: build", "Route: debug").replace("Phase: implement", "Phase: verify")
        text = "\n".join(line for line in base.splitlines() if not line.startswith("Retro:"))
        held = self.run_check("workflow", text, "--gate", "accept")
        self.assertEqual(held.returncode, 1, held.stderr)
        diagnostic = base.replace(self.retro, "Retro: n/a: diagnosis-only: findings delivered without a code fix\n")
        diagnostic = "\n".join(line for line in diagnostic.splitlines()
                               if not any(str(p) in line for p in self.closing_skills))
        result = self.run_check("workflow", diagnostic, "--gate", "accept")
        self.assertEqual(result.returncode, 0, result.stderr)
        build = diagnostic.replace("Route: debug", "Route: build")
        result = self.run_check("workflow", build, "--gate", "accept")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Retro exemption", result.stderr)

    def test_matt_brief_requires_actual_entry_fields(self):
        for field in ("Methodology", "Executor", "Route", "Phase", "Next gate", "Start", "DDD", "UX"):
            with self.subTest(field=field):
                text = "\n".join(l for l in self.workflow().splitlines()
                                 if not l.startswith(field + ":"))
                result = self.run_check("brief", self.brief() + text, "--matt")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(field, result.stderr)

    def assert_names_placeholder(self, stderr, line):
        """A refusal caused by angle-bracketed text quotes the line and says it looks like a placeholder."""
        self.assertIn(f"'{line[:80]}' looks like a placeholder", stderr)
        self.assertIn("write formats without angle brackets", stderr)

    def test_a_design_decisions_format_in_angle_brackets_is_named_as_a_placeholder(self):
        line = "Output format: <word> <count>, one pair per line, sorted by count"
        for name, plan in (
                ("design decisions", self.plan_text(decisions=f"{self.DECISIONS}\n{line}")),
                ("accepted scope", self.plan_text(scope=f'Accepted: "go" | chat.md#1\n{line}'))):
            with self.subTest(name):
                result = self.run_check("workflow", self.accept_with(plan), "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("needs one nonempty '## " + name.capitalize() + "' section", result.stderr)
                self.assert_names_placeholder(result.stderr, line)
        with self.subTest("a section refused for another reason names no placeholder"):
            result = self.run_check("workflow", self.accept_with(self.plan_text(decisions="TBD")), "--gate", "entry")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn("looks like a placeholder", result.stderr)

    def test_a_retro_section_with_a_bracketed_format_is_named_as_a_placeholder(self):
        line = "Findings per run: <count> <word>"
        self.retro_report.write_text(f"## Sources\nCurrent fixture session.\n## Findings\n{line}\n")
        retro = ("Retro: sha256:" + hashlib.sha256(self.retro_report.read_bytes()).hexdigest() +
                 f" | {self.retro_report}\n")
        text = self.workflow().replace(self.retro.split("Check:")[0], retro).replace("Phase: implement", "Phase: retro")
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Retro evidence needs one nonempty '## Findings' section", result.stderr)
        self.assert_names_placeholder(result.stderr, line)

    def test_a_done_means_line_with_a_bracketed_format_is_named_as_a_placeholder(self):
        line = "- output: prints <word> <count> for every input line"
        text = self.brief().replace("- behavior: check the artifact.", line) + self.workflow()
        result = self.run_check("brief", text, "--matt")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Matt Done means needs nonempty named claims and checks", result.stderr)
        self.assert_names_placeholder(result.stderr, line)
        with self.subTest("a Done means refused for a missing check names no placeholder"):
            bare = self.brief().replace("- behavior: check the artifact.", "- behavior") + self.workflow()
            result = self.run_check("brief", bare, "--matt")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn("looks like a placeholder", result.stderr)

    def test_a_workflow_field_with_a_bracketed_format_is_named_as_a_placeholder(self):
        for field, old, new in (
                ("Next gate", "test the changed behavior", "print <word> <count> lines"),
                ("DDD", "n/a: no unfamiliar API assumption", "n/a: no <vendor> API"),
                ("UX", "n/a: no journey change", "n/a: no <screen> change")):
            with self.subTest(field):
                line = f"{field}: {new}"
                result = self.run_check("workflow", self.workflow().replace(f"{field}: {old}", line), "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assert_names_placeholder(result.stderr, line)
        with self.subTest("a field refused for another reason names no placeholder"):
            result = self.run_check("workflow", self.workflow().replace("Phase: implement", "Phase: TBD"),
                                    "--gate", "entry")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn("looks like a placeholder", result.stderr)

    def test_a_bracketed_approval_check_or_snapshot_is_named_as_a_placeholder(self):
        line = "Accepted: the <word> <count> output | chat.md#1"
        result = self.run_check("workflow", self.accept_with(self.plan_text(scope=line)), "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_names_placeholder(result.stderr, line)
        check = "Check: behavior | passed | prints <word> <count>"
        result = self.run_check("workflow", self.workflow().replace("DDD:", check + "\nDDD:", 1), "--gate", "accept")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assert_names_placeholder(result.stderr, "behavior | passed | prints <word> <count>")

    def test_unresolved_or_placeholder_entry_does_not_pass(self):
        for field, old, new in (
            ("Start", "sha256:" + "a" * 64, "HEAD"),
            ("Phase", "implement", "TBD"),
            ("UX", "n/a: no journey change", "n/a"),
            ("DDD", "n/a: no unfamiliar API assumption", "unresolved"),
        ):
            with self.subTest(field=field):
                result = self.run_check("workflow", self.workflow().replace(
                    field + ": " + old, field + ": " + new), "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)

    def test_matt_mode_cannot_take_over_another_methodology(self):
        text = self.workflow().replace("Methodology: matt", "Methodology: other")
        general = self.run_check("brief", self.brief() + text)
        self.assertEqual(general.returncode, 0, general.stderr)
        matt = self.run_check("brief", self.brief() + text, "--matt")
        self.assertEqual(matt.returncode, 1, matt.stderr)

    def test_checked_heading_without_phase_items_is_insufficient(self):
        text = self.workflow().split("- [x]")[0]
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_selected_procedure_needs_a_recorded_read_before_work(self):
        text = "\n".join(l for l in self.workflow().splitlines()
                         if not l.startswith("Loaded:"))
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Loaded", result.stderr)

    def test_a_path_without_a_read_pointer_is_insufficient(self):
        text = self.workflow().replace(f" | worker: sha256:{self.procedure_digest} read event fixture-1 before work", "")
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_routing_procedure_cannot_be_silently_omitted(self):
        other = self.root / "implement" / "SKILL.md"
        other.parent.mkdir()
        other.write_text("An implementation procedure.\n")
        text = self.workflow().replace(str(self.router), str(other))
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Ask Matt", result.stderr)

    def test_procedure_files_must_be_available_to_the_executor(self):
        self.procedure.unlink()
        result = self.run_check("workflow", self.workflow(), "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_fenced_examples_cannot_supply_a_real_workflow(self):
        result = self.run_check("workflow", "```markdown\n" + self.workflow() + "```\n",
                                "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_workers_reuse_the_parent_checklist(self):
        parent = self.root / "state.md"
        parent.write_text("## Workflow\nExecutor: lead\n\n## Phase checklist\n- [x] Plan: evidence exists\n"
                          "- [ ] Implement: test pending\n")
        text = self.workflow().split("\n## Phase checklist")[0] + f"State: {parent}\n"
        result = self.run_check("brief", self.brief() + text, "--matt")
        self.assertEqual(result.returncode, 0, result.stderr)

    def artifact_snapshot(self):
        artifact = self.root / "reviewed.txt"
        artifact.write_text("reviewed behavior\n")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        return artifact, f"Snapshot: sha256:{digest} | {artifact}\n"

    def test_review_requires_the_actual_snapshot(self):
        result = self.run_check("workflow", self.workflow(), "--gate", "review")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Snapshot", result.stderr)

    def test_review_rejects_changed_non_git_artifacts(self):
        artifact, snapshot = self.artifact_snapshot()
        text = self.with_snapshot(self.workflow(), snapshot)
        before = self.run_check("workflow", text, "--gate", "review")
        self.assertEqual(before.returncode, 0, before.stderr)
        artifact.write_text("changed after review\n")
        after = self.run_check("workflow", text, "--gate", "review")
        self.assertEqual(after.returncode, 1, after.stderr)
        self.assertIn("changed", after.stderr)

    def test_final_gate_refuses_failed_or_missing_required_checks(self):
        _, snapshot = self.artifact_snapshot()
        for check in ("", "Check: behavior | failed | failing trace\n",
                      "Check: behavior | untested | browser unavailable\n",
                      "Check: behavior | passed | TBD\n"):
            with self.subTest(check=check):
                text = self.workflow().replace("\n## Phase checklist", "\n" + snapshot + check + "\n## Phase checklist")
                result = self.run_check("workflow", text, "--gate", "accept")
                self.assertEqual(result.returncode, 1, result.stderr)

    def test_final_acceptance_refuses_unfinished_execution_phases(self):
        _, snapshot = self.artifact_snapshot()
        text = (self.brief() + self.workflow()).replace("\n## Phase checklist", "\n" + snapshot +
                    "Check: behavior | passed | test trace at reviewed identity\n\n## Phase checklist")
        result = self.run_check("workflow", text, "--gate", "accept")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("unfinished", result.stderr)

    def test_final_acceptance_requires_original_named_outcomes(self):
        _, snapshot = self.artifact_snapshot()
        text = self.workflow().replace(IMPLEMENT_PENDING, STEPS_DONE).replace(
            "\n## Phase checklist", "\n" + snapshot +
            "Check: arbitrary | passed | unrelated passing command\n\n## Phase checklist")
        result = self.run_check("workflow", text, "--gate", "accept")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Done means", result.stderr)

    def test_final_gate_accepts_recorded_pass_at_the_reviewed_identity(self):
        _, snapshot = self.artifact_snapshot()
        text = (self.brief() + self.workflow()).replace(IMPLEMENT_PENDING, STEPS_DONE).replace(
            "\n## Phase checklist", "\n" + snapshot +
            "Check: behavior | passed | test trace at reviewed identity\n\n## Phase checklist")
        text += "- [ ] Report\n"
        result = self.run_check("workflow", text, "--gate", "accept")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_report_exception_cannot_hide_verification_or_earlier_work(self):
        _, snapshot = self.artifact_snapshot()
        base = (self.brief() + self.workflow()).replace(IMPLEMENT_PENDING, STEPS_DONE).replace(
            "\n## Phase checklist", "\n" + snapshot + "Check: behavior | passed | verified fixture\n\n## Phase checklist")
        for extra in ("- [ ] Verify/report: checks still owed\n", "- [ ] Report: premature\n- [x] Verify: trace\n", "- [ ] Report: one\n- [ ] Report: two\n"):
            with self.subTest(extra=extra):
                result = self.run_check("workflow", base + extra, "--gate", "accept")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("unfinished", result.stderr)

    def test_final_acceptance_uses_required_outcomes_in_the_authoritative_state(self):
        parent = self.root / "state.md"
        parent.write_text("## Workflow\nExecutor: lead\n\n## Done means\n- full-design: compare all approved panels\n"
                          "## Phase checklist\n" + STEPS_DONE + "- [ ] Report\n")
        _, snapshot = self.artifact_snapshot()
        text = self.brief() + self.workflow().split("\n## Phase checklist")[0] + f"State: {parent}\n" + snapshot
        text += "Check: behavior | passed | worker subset passed\n"
        held = self.run_check("workflow", text, "--gate", "accept")
        self.assertEqual(held.returncode, 1, held.stderr)
        self.assertIn("full-design", held.stderr)
        accepted = self.run_check("workflow", text + "Check: full-design | passed | all approved panels compared\n", "--gate", "accept")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_duplicate_outcome_names_cannot_hide_distinct_requirements(self):
        _, snapshot = self.artifact_snapshot()
        text = (self.brief() + self.workflow()).replace(IMPLEMENT_PENDING, STEPS_DONE).replace(
            "- behavior: check the artifact.", "- behavior: first requirement\n- behavior: omitted second requirement")
        text = text.replace("\n## Phase checklist", "\n" + snapshot + "Check: behavior | passed | only first check\n\n## Phase checklist")
        result = self.run_check("workflow", text, "--gate", "accept")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("unique", result.stderr)

    def test_ambiguous_required_work_cannot_disappear_at_acceptance(self):
        _, snapshot = self.artifact_snapshot()
        base = (self.brief() + self.workflow()).replace(IMPLEMENT_PENDING, STEPS_DONE).replace(
            "\n## Phase checklist", "\n" + snapshot + "Check: behavior | passed | verified fixture\n\n## Phase checklist")
        parent = self.root / "parent.md"
        parent.write_text("## Done means\n- behavior: complete parent requirement\n## Phase checklist\n- [x] Verify: trace checked\n")
        duplicate_local = base.replace("- behavior: check the artifact.", "- behavior: first part\n- behavior: hidden second part").replace("\n## Phase checklist", f"\nState: {parent}\n\n## Phase checklist")
        cases = {
            "malformed empty box": base + "- [] Verify: still required\n",
            "blocked box": base + "- [-] Verify: still required\n",
            "unmarked task": base + "- Verify: still required\n",
            "second outcome section": base + "## Done means\n- omitted: inspect missing design panel\n",
            "duplicate local names with parent": duplicate_local,
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                result = self.run_check("workflow", text, "--gate", "accept")
                self.assertEqual(result.returncode, 1, result.stderr)

    def test_final_gate_cannot_drop_a_declared_done_means_claim(self):
        _, snapshot = self.artifact_snapshot()
        brief = self.brief().replace("- behavior: check the artifact.",
                    "- behavior: check the artifact.\n- recovery: check the retry.")
        text = self.workflow().replace("\n## Phase checklist", "\n" + snapshot +
                    "Check: behavior | passed | behavior trace\n\n## Phase checklist")
        result = self.run_check("workflow", brief + text, "--gate", "accept")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("recovery", result.stderr)

    def test_matt_brief_cannot_use_an_empty_done_means_skeleton(self):
        text = self.brief().replace("- behavior: check the artifact.\n", "") + self.workflow()
        result = self.run_check("brief", text, "--matt")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Done means", result.stderr)

    def test_receipt_checks_the_matt_brief_as_well_as_the_return(self):
        receipt = ("\n## Return\nCloses: 1\n### Result\nReviewed fixture.\n"
                   "### Claims\n- behavior: passed at the fixture digest\n"
                   "### Evidence\nReview trace.\n" + self.load_lines())
        complete = self.run_check("receipt", self.brief() + self.workflow() + receipt, "--matt")
        self.assertEqual(complete.returncode, 0, complete.stderr)
        missing = self.run_check("receipt", self.brief() + receipt, "--matt")
        self.assertEqual(missing.returncode, 1, missing.stderr)
        self.assertIn("Workflow", missing.stderr)

    def matt_return(self, claims):
        return ("\n## Return\nCloses: 1\n### Result\nReviewed fixture.\n### Claims\n" + claims +
                "### Evidence\nReview trace.\n" + self.load_lines())

    def test_matt_receipt_refuses_a_renamed_done_means_claim(self):
        text = self.brief() + self.workflow() + self.matt_return("- behaviour: passed at fixture\n")
        general = self.run_check("receipt", text)
        self.assertEqual(general.returncode, 0, general.stderr)
        matt = self.run_check("receipt", text, "--matt")
        self.assertEqual(matt.returncode, 1, matt.stderr)
        self.assertIn("'behavior'", matt.stderr)

    def test_matt_receipt_refuses_a_duplicated_claim(self):
        text = self.brief() + self.workflow() + self.matt_return(
            "- behavior: passed at fixture\n- behavior: failed at fixture\n")
        matt = self.run_check("receipt", text, "--matt")
        self.assertEqual(matt.returncode, 1, matt.stderr)
        self.assertIn("duplicate", matt.stderr)

    def test_matt_receipt_refuses_a_claim_the_brief_never_declared(self):
        text = self.brief() + self.workflow() + self.matt_return(
            "- behavior: passed at fixture\n- extra: passed at fixture\n")
        matt = self.run_check("receipt", text, "--matt")
        self.assertEqual(matt.returncode, 1, matt.stderr)
        self.assertIn("'extra'", matt.stderr)

    def test_matt_receipt_refuses_a_second_claims_section(self):
        text = self.brief() + self.workflow() + self.matt_return(
            "- behavior: passed at fixture\n### Claims (corrected)\n- extra: failed at fixture\n")
        general = self.run_check("receipt", text)
        self.assertEqual(general.returncode, 0, general.stderr)
        matt = self.run_check("receipt", text, "--matt")
        self.assertEqual(matt.returncode, 1, matt.stderr)
        self.assertIn("exactly one Claims section", matt.stderr)

    def test_matt_receipt_ignores_claims_inside_a_fenced_example(self):
        text = self.brief() + self.workflow() + self.matt_return(
            "```text\n- behavior: passed at fixture\n```\n")
        general = self.run_check("receipt", text)
        self.assertEqual(general.returncode, 0, general.stderr)
        matt = self.run_check("receipt", text, "--matt")
        self.assertEqual(matt.returncode, 1, matt.stderr)
        self.assertIn("no status for Done means claim 'behavior'", matt.stderr)

    def test_matt_receipt_accepts_exact_coverage_with_failed_or_untested_status(self):
        brief = self.brief().replace("- behavior: check the artifact.\n",
                                     "- behavior: check the artifact.\n- speed: time it.\n")
        text = brief + self.workflow() + self.matt_return(
            "- behavior: failed at fixture\n- speed: untested no timer\n")
        matt = self.run_check("receipt", text, "--matt")
        self.assertEqual(matt.returncode, 0, matt.stderr)

    def test_preflight_does_not_require_the_lead_to_invent_worker_reads(self):
        text = "\n".join(l for l in self.workflow().splitlines() if not l.startswith("Loaded:"))
        result = self.run_check("brief", self.brief() + text, "--matt")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_receipt_does_not_substitute_lead_reads_for_the_worker(self):
        receipt = ("\n## Return\nCloses: 1\n### Result\nReview.\n"
                   "### Claims\n- behavior: passed at fixture\n### Evidence\n"
                   f"Loaded: {self.procedure} | lead: read event leader-1\n")
        result = self.run_check("receipt", self.brief() + self.workflow() + receipt, "--matt")
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_recorded_read_must_name_the_current_executor(self):
        text = self.workflow().replace("worker:", "lead:")
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_legacy_adapter_workflow_keeps_general_validation(self):
        text = self.brief() + "\n## Workflow\nMethodology: matt\nPhase: build\n"
        result = self.run_check("brief", text)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_git_snapshot_checks_the_current_working_tree(self):
        repo = self.root / "repo"
        repo.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(repo), *args],
                                  check=True, capture_output=True, text=True)
        git("init", "-b", "main")
        git("config", "user.name", "Fixture")
        git("config", "user.email", "fixture@example.invalid")
        artifact = repo / "app.txt"
        artifact.write_text("before\n")
        git("add", "app.txt")
        git("commit", "-m", "fixture")
        artifact.write_text("reviewed change\n")
        tool = Path.home() / ".agents" / "mifal" / "tools" / "review-snapshot.py"
        result = subprocess.run([sys.executable, "-B", str(tool), "--repo", str(repo),
                                 "--base", "main", "--path", "app.txt"],
                                check=True, capture_output=True, text=True)
        snapshot = self.root / "snapshot.json"
        snapshot.write_text(result.stdout)
        text = self.with_snapshot(self.workflow(), f"Snapshot: {snapshot}\n")
        current = self.run_check("workflow", text, "--gate", "review")
        self.assertEqual(current.returncode, 0, current.stderr)
        artifact.write_text("a later unreviewed edit\n")
        stale = self.run_check("workflow", text, "--gate", "review")
        self.assertEqual(stale.returncode, 1, stale.stderr)
        self.assertIn("Snapshot not current", stale.stderr)

    def test_malformed_snapshot_refuses_without_a_traceback(self):
        snapshot = self.root / "invalid.json"
        snapshot.write_text("not JSON")
        text = self.workflow().replace("\n## Phase checklist",
                    f"\nSnapshot: {snapshot}\n\n## Phase checklist")
        result = self.run_check("workflow", text, "--gate", "review")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_ddd_plan_cannot_substitute_scope_for_grounding(self):
        pool = Path.home() / ".agents/skills"
        scope = pool / "ddd-scope/SKILL.md"
        text = self.workflow().replace("Phase: implement", "Phase: plan").replace(
            "DDD: n/a: no unfamiliar API assumption", "DDD: applies: unfamiliar lifecycle")
        selection = f"Procedure: {scope}\nLoaded: {scope} | worker: sha256:{hashlib.sha256(scope.read_bytes()).hexdigest()} full read event scope\n"
        result = self.run_check("workflow", text.replace("\n## Phase checklist", "\n" + selection + "\n## Phase checklist"), "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("ddd-ground", result.stderr)

    def test_review_and_diagnosis_require_their_own_procedures(self):
        review = next(p for p in self.phase_skills if p.parent.name == "code-review")
        text = "\n".join(line for line in self.workflow().splitlines() if str(review) not in line)
        held = self.run_check("workflow", text.replace("Phase: implement", "Phase: review"), "--gate", "entry")
        self.assertEqual(held.returncode, 1, held.stderr)
        self.assertIn("code-review", held.stderr)
        debug = self.workflow().replace("Route: build", "Route: debug").replace("Phase: implement", "Phase: diagnose")
        held = self.run_check("workflow", debug, "--gate", "entry")
        self.assertEqual(held.returncode, 1, held.stderr)
        self.assertIn("diagnosing-bugs", held.stderr)

    def test_applicable_ux_requires_its_reference_read(self):
        text = self.workflow().replace("UX: n/a: no journey change", "UX: applies: form recovery changes")
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("UX applies", result.stderr)

    def test_ddd_plan_accepts_base_and_current_phase_bodies(self):
        text = self.workflow().replace("Phase: implement", "Phase: plan").replace(
            "DDD: n/a: no unfamiliar API assumption", "DDD: applies: unfamiliar lifecycle")
        selection = ""
        for name in ("ddd", "ddd-ground"):
            body = Path.home() / ".agents/skills" / name / "SKILL.md"
            selection += f"Procedure: {body}\nLoaded: {body} | worker: sha256:{hashlib.sha256(body.read_bytes()).hexdigest()} full read event grounding\n"
        result = self.run_check("workflow", text.replace("\n## Phase checklist", "\n" + selection + "\n## Phase checklist"), "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ambiguous_fields_are_rejected(self):
        text = self.workflow().replace("Methodology: matt", "Methodology: matt\nMethodology: matt")
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_bulleted_fields_and_adapter_skill_alias_parse_equally(self):
        text = self.workflow().replace("Procedure:", "Required skill paths:")
        text = "\n".join("- " + l if ": " in l and not l.startswith("- ") else l
                         for l in text.splitlines())
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_partial_read_cannot_satisfy_a_selected_body(self):
        text = self.workflow().replace("read event fixture-1 before work", "partial: first three lines only")
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("partial", result.stderr)

    def test_partial_byte_count_cannot_use_the_complete_body_hash(self):
        text = self.workflow().replace(f"sha256:{self.procedure_digest} read", f"sha256:{self.procedure_digest} bytes:1 read")
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("byte count", result.stderr)

    def test_complete_byte_count_preserves_unicode_and_crlf_body_identity(self):
        self.procedure.write_bytes("Full body: שלום 😀\r\nSecond line.\r\n".encode("utf-8"))
        self.procedure_digest = hashlib.sha256(self.procedure.read_bytes()).hexdigest()
        text = self.workflow().replace(f"sha256:{self.procedure_digest} read", f"sha256:{self.procedure_digest} bytes:{len(self.procedure.read_bytes())} complete read")
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_complete_read_pointer_can_describe_unlimited_output(self):
        text = self.workflow().replace("read event fixture-1 before work", "complete read event: no offset or limit; not a partial read")
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_read_command_emits_the_entire_body_with_an_exact_buffer_footer(self):
        data = "α😀\r\n".encode("utf-8")
        self.procedure.write_bytes(data)
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "read", str(self.procedure)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertTrue(result.stdout.startswith(data))
        footer = result.stdout[len(data):].decode()
        self.assertIn("sha256:" + hashlib.sha256(data).hexdigest(), footer)
        self.assertIn("bytes:8", footer)
        self.assertIn("end of body", footer)

    def test_malformed_byte_count_is_not_treated_as_a_read_pointer(self):
        for count in ("TBD", "-1", "1.5"):
            with self.subTest(count=count):
                text = self.workflow().replace(f"sha256:{self.procedure_digest} read", f"sha256:{self.procedure_digest} bytes:{count} read")
                result = self.run_check("workflow", text, "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("byte count", result.stderr)

    def test_skill_update_invalidates_a_recorded_old_read(self):
        text = self.workflow()
        self.procedure.write_text("Updated custom procedure with a new required gate.\n")
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("changed", result.stderr)

    def test_entry_body_cannot_be_silently_omitted(self):
        text = "\n".join(l for l in self.workflow().splitlines()
                         if str(self.entry) not in l)
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Engineering Workflow", result.stderr)

    def test_same_named_stub_cannot_replace_a_canonical_core_body(self):
        for name, original, digest in (("ask-matt", self.router, self.router_digest),
                                       ("engineering-workflow", self.entry, self.entry_digest)):
            with self.subTest(name=name):
                fake = self.root / name / "SKILL.md"
                fake.parent.mkdir()
                fake.write_text("Local stub, not the shared methodology.\n")
                fake_digest = hashlib.sha256(fake.read_bytes()).hexdigest()
                text = self.workflow().replace(str(original), str(fake)).replace(digest, fake_digest)
                result = self.run_check("workflow", text, "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)

    def test_unknown_optional_workflow_keys_cannot_silently_fall_back(self):
        for key in ("Snaphsot", "Satte", "Procedrue"):
            with self.subTest(key=key):
                text = self.workflow().replace("Phase: implement", f"Phase: implement\n{key}: ignored.txt")
                result = self.run_check("workflow", text, "--gate", "entry")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("unknown Workflow field", result.stderr)

    def test_current_return_cannot_borrow_a_previous_attempts_reads(self):
        receipt = ("\n## Return\nCloses: 1\n### Result\nOld completed attempt.\n"
                   "### Claims\n- behavior: passed\n### Evidence\n" + self.load_lines() +
                   "\n## Return\nCloses: 1\n### Result\nAn older attempt.\n"
                   "### Claims\n- behavior: passed\n### Evidence\n" + self.load_lines())
        text = self.brief().replace("task: 1\n", "task: 1\nattempt: 1.1\n") + self.workflow() + receipt
        general = self.run_check("receipt", text)
        self.assertEqual(general.returncode, 0, general.stderr)
        matt = self.run_check("receipt", text, "--matt")
        self.assertEqual(matt.returncode, 1, matt.stderr)
        self.assertIn("current task/attempt", matt.stderr)

    def test_canonical_symlink_aliases_are_accepted(self):
        alias = self.root / "router-alias.md"
        alias.symlink_to(self.router)
        result = self.run_check("workflow", self.workflow().replace(str(self.router), str(alias)),
                                "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_applicable_disciplines_require_canonical_bodies(self):
        pool = Path.home() / ".agents" / "skills"
        for field, relative in (("UX", "team-lead/references/ux-acceptance.md"),
                                 ("DDD", "ddd-ground/SKILL.md")):
            with self.subTest(field=field):
                real = (pool / relative).resolve()
                fake = self.root / relative
                fake.parent.mkdir(parents=True)
                fake.write_text("Same-named discipline stub.\n")
                base = self.workflow()
                old = "UX: n/a: no journey change" if field == "UX" else "DDD: n/a: no unfamiliar API assumption"
                base = base.replace(old, f"{field}: applies: affected behavior")
                if field == "DDD":
                    ddd = (pool / "ddd/SKILL.md").resolve()
                    selected_base = f"Procedure: {ddd}\nLoaded: {ddd} | worker: sha256:{hashlib.sha256(ddd.read_bytes()).hexdigest()} full read event base\n"
                    base = base.replace("Phase: implement", "Phase: plan").replace("\n## Phase checklist", "\n" + selected_base + "\n## Phase checklist")

                for source, expected in ((fake, 1), (real, 0)):
                    digest = hashlib.sha256(source.read_bytes()).hexdigest()
                    selected = (f"Procedure: {source}\nLoaded: {source} | worker: sha256:{digest} read event discipline\n")
                    text = base.replace("\n## Phase checklist", "\n" + selected + "\n## Phase checklist")
                    result = self.run_check("workflow", text, "--gate", "entry")
                    self.assertEqual(result.returncode, expected, result.stderr)

    def test_adapter_metadata_fields_remain_supported(self):
        text = self.workflow().replace("Phase: implement", "Phase: implement\nScheduler: native\nIntegration owner: worker")
        result = self.run_check("workflow", text, "--gate", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)


    # ---- strict acceptance grammar and snapshot guards (Task 12)

    def test_final_open_item_is_exactly_report(self):
        for tail, expected in (("- [ ] Report\n", 0),
                               ("- [ ] Report: also implement the remaining slice\n", 1),
                               ("- [ ] Report \u2014 deliver the result\n", 1),
                               ("- [ ] Reporting\n", 1), ("- [ ] report\n", 1)):
            with self.subTest(tail=tail):
                result = self.run_check("workflow", self.completed_workflow() + tail, "--gate", "accept")
                self.assertEqual(result.returncode, expected, result.stderr)
                if expected:
                    self.assertIn("unfinished", result.stderr)
                    self.assertIn("exactly '- [ ] Report'", result.stderr)
                    self.assertIn("Next gate", result.stderr)

    def test_malformed_checklist_markers_hold_every_gate(self):
        for marker in ("* [ ] Verify", "+ [ ] Verify", "-[ ] Verify", "1. [ ] Verify", "1) [ ] Verify",
                       "  * [x] Verify", "- [~] Verify", "-Verify"):
            for gate in ("entry", "accept"):
                with self.subTest(marker=marker, gate=gate):
                    base = self.completed_workflow() if gate == "accept" else self.workflow()
                    result = self.run_check("workflow", base + marker + "\n- [ ] Report\n", "--gate", gate)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("malformed task item", result.stderr)

    def test_checklist_prose_that_only_looks_like_a_marker_stays_legal(self):
        prose = "Scale factor 1.5 applies.\n**Bold note** about the plan.\n*Emphasis* is prose.\n"
        result = self.run_check("workflow", self.completed_workflow() + prose + "- [ ] Report\n", "--gate", "accept")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_done_means_marker_lines_must_be_dash_claims(self):
        for bad in ("1. hidden-claim: must also pass", "2) hidden-claim: must also pass",
                    "* hidden-claim: must also pass", "+ hidden-claim: must also pass",
                    "-hidden-claim: must also pass"):
            with self.subTest(bad=bad):
                brief = self.brief().replace("- behavior: check the artifact.\n",
                                             "- behavior: check the artifact.\n" + bad + "\n")
                result = self.run_check("brief", brief + self.workflow(), "--matt")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("Done means", result.stderr)
                self.assertIn("- <claim>: <check>", result.stderr)
                accepted = self.completed_workflow().replace(
                    "- behavior: check the artifact.\n", "- behavior: check the artifact.\n" + bad + "\n")
                result = self.run_check("workflow", accepted + "- [ ] Report\n", "--gate", "accept")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("- <claim>: <check>", result.stderr)

    def test_done_means_prose_stays_legal(self):
        brief = self.brief().replace("- behavior: check the artifact.\n",
                                     "The decisive checks follow, about 1.5 per claim.\n- behavior: check the artifact.\n")
        result = self.run_check("brief", brief + self.workflow(), "--matt")
        self.assertEqual(result.returncode, 0, result.stderr)

    def diff_snapshot(self, name="owned-delta.diff", create=True):
        artifact = self.root / name
        body = "diff --git a/app.txt b/app.txt\n--- a/app.txt\n+++ b/app.txt\n@@ -1 +1 @@\n-before\n+after\n"
        if create:
            artifact.write_text(body)
        digest = hashlib.sha256(body.encode()).hexdigest()
        return artifact, f"Snapshot: sha256:{digest} | {artifact}\n"

    def with_snapshot(self, text, snapshot):
        """Pin the review identity; the work under review is done, as the review gate requires."""
        return text.replace(IMPLEMENT_PENDING, STEPS_BEFORE_REVIEW).replace(
            "\n## Phase checklist", "\n" + snapshot + "\n## Phase checklist", 1)

    def test_frozen_diff_cannot_identify_live_build_or_debug_code(self):
        for route, phase in (("build", "implement"), ("debug", "verify")):
            for name in ("owned-delta.diff", "owned.patch", "OWNED.DIFF"):
                with self.subTest(route=route, name=name):
                    _, snapshot = self.diff_snapshot(name)
                    text = self.with_snapshot(self.workflow().replace("Route: build", "Route: " + route)
                                              .replace("Phase: implement", "Phase: " + phase), snapshot)
                    result = self.run_check("workflow", text, "--gate", "review")
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("frozen diff", result.stderr)
                    self.assertIn("heuristic", result.stderr)

    def test_frozen_diff_shortcut_is_refused_before_any_file_read(self):
        _, snapshot = self.diff_snapshot(create=False)
        text = self.with_snapshot(self.workflow(), snapshot)
        result = self.run_check("workflow", text, "--gate", "review")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("frozen diff", result.stderr)
        self.assertNotIn("unavailable", result.stderr)

    def test_frozen_diff_guard_leaves_review_and_diagnosis_routes_alone(self):
        _, snapshot = self.diff_snapshot()
        review = self.with_snapshot(self.workflow().replace("Route: build", "Route: review")
                                    .replace("Phase: implement", "Phase: review"), snapshot)
        result = self.run_check("workflow", review, "--gate", "review")
        self.assertEqual(result.returncode, 0, result.stderr)
        base = self.completed_workflow().replace("Route: build", "Route: debug").replace("Phase: implement", "Phase: verify")
        diagnostic = base.replace(self.retro, "Retro: n/a: diagnosis-only: findings delivered without a code fix\n")
        diagnostic = "\n".join(line for line in diagnostic.splitlines()
                               if not any(str(p) in line for p in self.closing_skills))
        old = next(line for line in diagnostic.splitlines() if line.startswith("Snapshot:"))
        diagnostic = diagnostic.replace(old, snapshot.strip())
        result = self.run_check("workflow", diagnostic + "\n- [ ] Report\n", "--gate", "accept")
        self.assertEqual(result.returncode, 0, result.stderr)

    def empty_scope_snapshot(self):
        repo = self.root / "repo"
        repo.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
        git("init", "-b", "main")
        git("config", "user.name", "Fixture")
        git("config", "user.email", "fixture@example.invalid")
        (repo / "app.txt").write_text("before\n")
        git("add", "app.txt")
        git("commit", "-m", "fixture")
        tool = Path.home() / ".agents" / "mifal" / "tools" / "review-snapshot.py"
        result = subprocess.run([sys.executable, "-B", str(tool), "--repo", str(repo), "--base", "main",
                                 "--path", "app.txt"], check=True, capture_output=True, text=True)
        snapshot = self.root / "empty-snapshot.json"
        snapshot.write_text(result.stdout)
        self.assertFalse(json.loads(result.stdout)["reviewable"], "fixture must have an empty scope")
        return f"Snapshot: {snapshot}\n"

    def test_empty_json_snapshot_cannot_close_build_or_debug_work(self):
        snapshot = self.empty_scope_snapshot()
        for route, phase in (("build", "implement"), ("debug", "verify")):
            with self.subTest(route=route):
                text = self.with_snapshot(self.workflow().replace("Route: build", "Route: " + route)
                                          .replace("Phase: implement", "Phase: " + phase), snapshot)
                result = self.run_check("workflow", text, "--gate", "review")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("reviewable: false", result.stderr)
        review = self.with_snapshot(self.workflow().replace("Route: build", "Route: review")
                                    .replace("Phase: implement", "Phase: review"), snapshot)
        result = self.run_check("workflow", review, "--gate", "review")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_snapshot_guards_keep_the_callers_bounded_reader_and_digest(self):
        spec = importlib.util.spec_from_file_location("contracts_under_test", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        blob = self.root / "blob.bin"
        blob.write_bytes(b"\xff\x00binary artifact\x01")
        reads, digests = [], []

        def read_text(path):
            reads.append(Path(path).name)
            return Path(path).read_bytes().decode("utf-8")

        def body_digest(path):
            digests.append(Path(path).name)
            return "b" * 64 if Path(path).name == "blob.bin" else module.workflow_digest(Path(path))

        def check(snapshot_line):
            reads.clear()
            digests.clear()
            text = self.with_snapshot(self.workflow(), snapshot_line)
            return module.validate_workflow(text, self.record, gate="review",
                                            read_text=read_text, body_digest=body_digest)

        self.assertEqual(check(f"Snapshot: sha256:{'b' * 64} | {blob}\n"), [])
        self.assertIn("blob.bin", digests)
        _, diff_line = self.diff_snapshot(create=False)
        errors = check(diff_line)
        self.assertTrue(any("frozen diff" in e for e in errors), errors)
        self.assertNotIn("owned-delta.diff", reads + digests)
        errors = check(self.empty_scope_snapshot())
        self.assertTrue(any("reviewable: false" in e for e in errors), errors)
        self.assertIn("empty-snapshot.json", reads)

    def bounded(self, args, seconds=10):
        # Every special-file check runs in a child under an external bound below the 15 s snapshot-checker
        # timeout, so a regression that blocks in open() fails here instead of hanging the suite.
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=seconds)
        except subprocess.TimeoutExpired:
            self.fail(f"blocked past {seconds}s on a special file instead of refusing it")

    def special_files(self):
        fifo = self.root / "snapshot.fifo"
        os.mkfifo(fifo)
        link = self.root / "snapshot-link.json"
        link.symlink_to(fifo)
        return {"fifo": fifo, "symlink to fifo": link, "directory": self.procedure.parent,
                "device": Path("/dev/null")}

    def test_special_file_snapshot_is_refused_before_the_snapshot_checker_times_out(self):
        for name, target in self.special_files().items():
            with self.subTest(special=name):
                self.record.write_text(self.with_snapshot(self.workflow(), f"Snapshot: {target}\n"))
                result = self.bounded([sys.executable, "-B", str(SCRIPT), "workflow", str(self.record),
                                       "--gate", "review"])
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("Snapshot cannot be read", result.stderr)
                if name != "directory":
                    self.assertIn("not a regular file", result.stderr)

    def test_special_file_state_record_is_refused_without_blocking(self):
        fifo = self.special_files()["fifo"]
        self.record.write_text(self.with_snapshot(self.workflow(), f"State: {fifo}\n"))
        result = self.bounded([sys.executable, "-B", str(SCRIPT), "workflow", str(self.record), "--gate", "entry"])
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("cannot read State checklist", result.stderr)
        self.assertIn("not a regular file", result.stderr)

    DIGEST_PROBE = (
        "import importlib.util, json, os, sys, tracemalloc\n"
        "from pathlib import Path\n"
        "spec = importlib.util.spec_from_file_location('contracts_probe', sys.argv[1])\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "fds = lambda: sorted(int(name) for name in os.listdir('/dev/fd'))\n"
        "before = fds()\n"
        "tracemalloc.start()\n"
        "try:\n"
        "    outcome = {'digest': module.workflow_digest(Path(sys.argv[2]))}\n"
        "except OSError as error:\n"
        "    outcome = {'error': type(error).__name__, 'message': str(error)}\n"
        "outcome['peak'] = tracemalloc.get_traced_memory()[1]\n"
        "outcome['leaked'] = [fd for fd in fds() if fd not in before]\n"
        "print(json.dumps(outcome))\n")

    def digest_probe(self, target):
        result = self.bounded([sys.executable, "-B", "-I", "-c", self.DIGEST_PROBE, str(SCRIPT), str(target)])
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_default_digest_refuses_special_files_and_closes_the_descriptor(self):
        for name, target in self.special_files().items():
            with self.subTest(special=name):
                outcome = self.digest_probe(target)
                self.assertIn("error", outcome, outcome)
                if name != "directory":
                    self.assertIn("not a regular file", outcome["message"])
                self.assertEqual(outcome["leaked"], [], "the refused open must not leak a descriptor")

    def test_default_digest_still_streams_a_regular_file(self):
        big = self.root / "big.bin"
        data = bytes(range(256)) * (8 * 4096) + b"tail"
        big.write_bytes(data)
        outcome = self.digest_probe(big)
        self.assertEqual(outcome["digest"], hashlib.sha256(data).hexdigest())
        self.assertEqual(outcome["leaked"], [])
        self.assertLess(outcome["peak"], 2 * 1024 * 1024, "the digest must not hold the whole 8 MiB file")


if __name__ == "__main__":
    unittest.main()
