"""The one reload (ticket 08): what the entry and Team Lead teach, pinned in the files an agent reads.

Prose cannot be run. These tests pin the forms an agent is taught, and where the validator has a seam they run
the taught form through it: each taught line is filled in and handed to the public CLI, and the griller
brief template is filled in and checked by `brief --matt`, so the teaching and the gate cannot drift apart.
They do not show that an agent follows the text.
"""
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from test_workflow_cuts import NO_BRANCH, StepFixture, steps

SCRIPT = Path(__file__).with_name("validate_contracts.py")
SKILLS = Path(__file__).resolve().parents[2]
ENTRY = SKILLS / "engineering-workflow" / "SKILL.md"
TEAM_LEAD = SKILLS / "team-lead" / "SKILL.md"
COMMUNICATION = SKILLS / "team-lead" / "references" / "communication.md"
TEAM_MEMORY = SKILLS / "team-lead" / "references" / "team-memory.md"
HERDR = SKILLS / "team-lead" / "references" / "herdr.md"
PHASE_RECORD = SKILLS / "engineering-workflow" / "references" / "phase-record.md"
WORKFLOW_MAP = SKILLS / "engineering-workflow" / "references" / "workflow-map.md"
OWNER_SENTENCE = "Matt owns engineering in every harness."
# sha256 prefix of a retired methodology's name, hashed so this file names none (as tests/test_content.py does)
RETIRED_OWNER = "87ac976952264a7b"

CHECK_FORM = "Check: start <step> | passed | <evidence> at:<UTC>"
STEP_DEFINED = "`<step>` is a name from the workflow map's Required steps"
CUT_FORM = "Cut: <steps> | <quote> | <source>"
ROUTE_FORM = "Route decision:"
PHASES = ("scope", "research", "resolve design", "plan", "build", "review", "verify", "retro")


def prose(path):
    """The file with every run of whitespace collapsed, so a re-wrapped line does not break a pin."""
    return " ".join(path.read_text().split())


def taught(body, prefix):
    """The backticked line starting `prefix` that `body` teaches, as written."""
    found = re.search(r"`(" + re.escape(prefix) + r"[^`]+)`", prose(body))
    assert found, f"{body.parent.name} teaches no `{prefix}...` line"
    return found.group(1)


def validator(*args):
    return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], capture_output=True, text=True)


class DefaultOwnerTests(unittest.TestCase):
    def test_the_entry_makes_matt_the_owner_in_every_harness_without_a_launcher(self):
        text = prose(ENTRY)
        self.assertIn(OWNER_SENTENCE, text)
        words = {hashlib.sha256(w.encode()).hexdigest()[:16] for w in re.findall(r"[a-z0-9]+", text.lower())}
        self.assertNotIn(RETIRED_OWNER, words)


class TheGateIsLoggedTests(StepFixture):
    """The taught `Check:` line is the one the validator holds a late read against."""

    def test_both_bodies_teach_the_gate_before_every_dispatch_review_and_acceptance_as_a_check_line(self):
        for body in (ENTRY, TEAM_LEAD):
            with self.subTest(body=body.parent.name):
                text = prose(body)
                self.assertIn(CHECK_FORM, text)
                self.assertRegex(text, r"(?i)before every (build/)?dispatch")
                self.assertIn("--gate entry|review|accept", text)
                self.assertIn("brief <brief> --matt", text)

    def test_the_taught_check_line_is_one_the_gate_holds_a_late_read_against(self):
        line = taught(ENTRY, "Check: start").replace("<step>", "implement").replace(
            "<evidence>", "brief --matt exit 0").replace("<UTC>", "2026-10-17T10:00:00Z")

        def reads_stamped(when):
            text = self.record(steps("Scope", "Grilling", pending=("Implement",)),
                               NO_BRANCH + " at:2026-10-17T09:00:00Z", phase="implement", extra=line + "\n")
            return "\n".join(f"{row} at:{when}" if row.startswith("Loaded:") else row
                             for row in text.splitlines()) + "\n"

        self.passes(reads_stamped("2026-10-17T09:59:00Z"))
        self.refused(reads_stamped("2026-10-17T10:05:00Z"), "after", "start Check")


class StartChecksNameAStepTests(StepFixture):
    """Correction 28.2 part 2: `<step>` in `Check: start <step>` is defined where it is taught, and the validator reads it."""
    BODIES = (ENTRY, TEAM_LEAD, PHASE_RECORD)

    def line(self, step):
        return taught(ENTRY, "Check: start").replace("<step>", step).replace(
            "<evidence>", "gate exit 0").replace("<UTC>", "2026-10-17T10:00:00Z")

    def at_implement(self, line):
        return self.record(steps("Scope", "Grilling", pending=("Implement",)),
                           NO_BRANCH + " at:2026-10-17T09:00:00Z", phase="implement", extra=line + "\n")

    def test_every_teaching_file_names_the_step_and_none_still_says_phase(self):
        for body in self.BODIES:
            with self.subTest(body=body.parent.name):
                text = prose(body)
                self.assertIn("Check: start <step> | passed |", text)
                self.assertNotIn("Check: start <phase>", text)

    def test_every_teaching_file_defines_the_step_and_refuses_an_unknown_name(self):
        for body in self.BODIES:
            with self.subTest(body=body.parent.name):
                text = prose(body)
                self.assertIn(STEP_DEFINED, text)
                self.assertRegex(text, r"(?i)the route's phase word")
                self.assertRegex(text, r"(?i)`start entry`[^.]{0,40}refused")

    def test_every_step_the_entry_lists_is_a_name_the_validator_reads(self):
        listed = re.search(r"Required steps \(([^)]+)\)", prose(ENTRY))
        self.assertTrue(listed, "the entry lists no step names after 'Required steps ('")
        names = [name.strip(" `") for name in listed.group(1).split(",")]
        self.assertEqual(names, ["scope", "grilling", "to-spec", "to-tickets", "implement", "review", "retro"])
        for name in names:
            with self.subTest(step=name):
                self.passes(self.at_implement(self.line(name)))

    def test_an_unknown_name_such_as_entry_is_refused(self):
        self.refused(self.at_implement(self.line("entry")), "unknown step 'entry'")

    def test_the_lead_logs_a_start_check_as_each_step_begins_to_spec_included(self):
        for body in (ENTRY, TEAM_LEAD):
            with self.subTest(body=body.parent.name):
                text = prose(body)
                self.assertRegex(text, r"(?i)as each step begins")
                self.assertIn("`Check: start to-spec`", text)

    def test_a_reload_is_a_second_loaded_line_beside_the_original(self):
        for body in (ENTRY, TEAM_LEAD, PHASE_RECORD):
            with self.subTest(body=body.parent.name):
                self.assertRegex(prose(body), r"(?i)reload[^.]{0,120}(add|write)[^.]{0,40}new `Loaded:` line beside the original")

    def test_the_read_rule_in_the_phase_record_is_the_one_the_validator_holds(self):
        text = prose(PHASE_RECORD)
        self.assertRegex(text, r"(?i)at least one `Loaded:` (line|read) [^.]{0,80}no later than the earliest")
        self.assertRegex(text, r"(?i)later reload never makes an earlier on-time read late")
        for governed in ("grilling, grill-with-docs and domain-modeling", "to-spec", "to-tickets", "implement and tdd",
                         "code-review", "retro"):
            self.assertIn(governed, text)
        self.assertNotRegex(text, r"(?i)earliest start Check of any phase")


class RouteDecisionIsStampedTests(StepFixture):
    """Correction 28.2 part 2 (F31-3): the taught Route decision carries the stamp the validator asks for."""
    START = "Check: start implement | passed | gate exit 0 at:2026-10-17T10:00:00Z\n"

    def test_both_bodies_and_the_phase_record_teach_the_stamp(self):
        for body in (ENTRY, TEAM_LEAD):
            with self.subTest(body=body.parent.name):
                self.assertRegex(prose(body), r"Route decision:? [^`]*at:<UTC>")
        shown = [row for row in PHASE_RECORD.read_text().splitlines() if row.startswith("Route decision: multi-session")]
        self.assertEqual(len(shown), 2, shown)
        for row in shown:
            self.assertTrue(row.endswith("at:<UTC>"), row)

    def test_the_taught_line_filled_in_passes_and_without_its_stamp_is_refused(self):
        line = taught(ENTRY, "Route decision: multi-session").replace("<why>", "a one-file fix").replace(
            "<UTC>", "2026-10-17T09:00:00Z")
        decision = line.removeprefix("Route decision: ")
        done = steps("Scope", "Grilling", "Implement", pending=("Review",))
        self.passes(self.record(done, decision, phase="implement", extra=self.START))
        unstamped = decision.replace(" at:2026-10-17T09:00:00Z", "")
        self.refused(self.record(done, unstamped, phase="implement", extra=self.START), "Route decision", "at:")


class OpeningQuestionTests(unittest.TestCase):
    def test_the_question_comes_before_the_first_edit_or_dispatch_so_a_solo_agent_is_covered(self):
        for body in (ENTRY, TEAM_LEAD):
            with self.subTest(body=body.parent.name):
                text = prose(body)
                self.assertRegex(text, r"(?i)before the first edit or dispatch,? [^.]{0,40}full workflow or cut\?")
                self.assertNotRegex(text, r"(?i)before the first dispatch,? ask")


class FullWorkflowTests(StepFixture):
    def test_both_bodies_teach_the_full_workflow_default_and_the_opening_question(self):
        for body in (ENTRY, TEAM_LEAD):
            with self.subTest(body=body.parent.name):
                text = prose(body)
                self.assertIn("full workflow or cut?", text)
                self.assertRegex(text, r"(?i)silence is not a cut")
                self.assertIn(CUT_FORM, text)
                self.assertIn(ROUTE_FORM, text)
        self.assertRegex(prose(TEAM_LEAD), r"(?i)branch that drops a main-flow step")

    def test_the_taught_cut_line_is_one_the_gate_accepts_for_a_missing_step(self):
        skipped = steps("Scope", "Implement")
        with tempfile.TemporaryDirectory() as folder:
            decisions = Path(folder) / "decisions.md"
            decisions.write_text('# Decisions\n\n## 2026-10-17\n\n"skip the interview, just build it"\n')
            line = taught(ENTRY, "Cut:").replace("<steps>", "grilling").replace(
                "<quote>", '"skip the interview, just build it"').replace("<source>", f"{decisions}#2026-10-17")
            self.refused(self.record(skipped), "'grilling'")
            self.passes(self.record(skipped, extra=line + "\n"))


class LocalOverrideTests(unittest.TestCase):
    def test_both_bodies_record_the_two_local_overrides(self):
        for body in (ENTRY, TEAM_LEAD):
            with self.subTest(body=body.parent.name):
                text = prose(body)
                self.assertRegex(text, r"(?i)under Team Lead,? the grilled user is the lead")
                self.assertRegex(text, r"(?i)distributed grilling feeds to-spec")


class ConsultMatrixTests(unittest.TestCase):
    def matrix(self):
        text = prose(TEAM_MEMORY)
        found = re.search(r"`Consult: ([^`]+)`", text)
        assert found, "team-memory.md shows no `Consult: ...` example line"
        return dict(pair.strip().rsplit(": ", 1) for pair in found.group(1).split(";"))

    def test_the_agreement_carries_one_level_per_phase_and_a_default(self):
        rows = self.matrix()
        self.assertEqual(set(rows), set(PHASES) | {"default"})
        self.assertTrue(set(rows.values()) <= {"high", "medium", "low"}, rows)

    def test_the_example_is_the_recommended_setting(self):
        rows = self.matrix()
        self.assertEqual({k for k, v in rows.items() if v == "high"}, {"scope", "resolve design"})
        self.assertEqual(rows["default"], "low")

    def test_no_level_moves_what_only_the_human_decides(self):
        text = prose(TEAM_MEMORY)
        self.assertRegex(text, r"(?i)reserved actions? and plan acceptance (always )?(go|come) to the human")
        self.assertRegex(text, r"(?i)consult(ation|ing)? never (expands|widens) authority")

    def test_the_lead_asks_once_with_a_recommended_matrix(self):
        self.assertRegex(prose(TEAM_LEAD), r"(?i)Consult matrix[^.]*once[^.]*recommended")


class GrillerBriefTests(unittest.TestCase):
    """The griller brief template, filled in, is a brief the Matt gate accepts."""
    PLACEHOLDER = re.compile(r"<[^<>\n]+>")

    def template(self):
        text = COMMUNICATION.read_text()
        found = re.search(r"^#+ The griller's brief\n(.*?)^```text\n(.*?)^```\n", text, re.S | re.M)
        assert found, "communication.md has no 'The griller's brief' section with a ```text template"
        return found.group(2)

    def fill(self, template, root, plan):
        pool = Path.home() / ".agents" / "skills"
        digest = "sha256:" + hashlib.sha256(plan.read_bytes()).hexdigest()
        rules = ((r"<n>", "2"), (r"<k>", "1"), (r"<cap>", "3"), (r"<griller>", "griller"),
                 (r"<record root>", str(root)), (r"<pool>", str(pool)), (r"<plan path>", str(plan)),
                 (r"<[^<>\n]*digest[^<>\n]*>", digest.split(":", 1)[1]),
                 (r"<[^<>\n]*decisions under test[^<>\n]*>", "the design decisions of the fixture plan"),
                 (r"<[^<>\n]*>", "fixture value"))
        for pattern, value in rules:
            template = re.sub(pattern, value, template)
        return template

    def test_the_filled_template_passes_the_matt_brief_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / "plan.md"
            plan.write_text("## Accepted scope\nA fixture.\n## Design decisions\nUse the existing interface.\n")
            (root / "state.md").write_text("## Phase checklist\n- [x] Scope: asked\n- [x] Inspect: read\n"
                                           "- [ ] Resolve: the interview runs\n")
            brief = root / "task.md"
            brief.write_text(self.fill(self.template(), root, plan))
            result = validator("brief", str(brief), "--matt")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_template_names_the_round_files_the_return_lines_and_an_empty_frontier(self):
        template = self.template()
        for needed in ("round-<k>.md", "answers-<k>.md", "Plan path:", "Design digest:", "Frontier: empty",
                       "design-digest", "Never ring ROUND", "Route: plan", "Phase: resolve", "Grilling: interview:"):
            self.assertIn(needed, template)
        self.assertRegex(template, r"(?i)files? (are|is) authoritative")

    def test_the_griller_checks_its_own_return_with_the_receipt_gate_before_it_rings_done(self):
        bullet = next(row for row in self.template().splitlines() if "design-digest" in row)
        self.assertRegex(bullet, r"validate_contracts\.py receipt [^`]*<n>\.md --matt")
        self.assertLess(bullet.index("receipt"), bullet.index("ring `DONE"))

    def test_the_taught_receipt_command_is_a_valid_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / "plan.md"
            plan.write_text("## Accepted scope\nA fixture.\n")
            task = root / "task.md"
            task.write_text(self.fill(self.template(), root, plan))
            result = validator("receipt", str(task), "--matt")
            self.assertNotIn("usage:", result.stderr)

    def test_every_ring_the_template_teaches_is_a_valid_doorbell_and_round_is_not(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / "plan.md"
            plan.write_text("## Accepted scope\nA fixture.\n## Design decisions\nUse the existing interface.\n")
            rings = re.findall(r"`((?:HELP|DONE) [^`]+)`", self.fill(self.template(), root, plan))
            self.assertEqual(sorted({ring.split()[0] for ring in rings}), ["DONE", "HELP"], rings)
            self.assertTrue(any("grilling round 1:" in ring for ring in rings), rings)
            for ring in rings:
                with self.subTest(ring=ring):
                    self.assertEqual(validator("doorbell", ring).returncode, 0, ring)
        self.assertEqual(validator("doorbell", "ROUND 1 2").returncode, 1)


class TheFirstRefusalTeachesTests(unittest.TestCase):
    """A stranger's first `brief --matt` lacks the Workflow section; the refusal shows one."""

    FRONTMATTER = "---\ntask: 7\nowner: kai\nlatitude: do-tell\nreturn: .team/tasks/7.md\n---\n# Task\n"

    def refusal(self, body):
        with tempfile.TemporaryDirectory() as d:
            brief = Path(d) / "7.md"
            brief.write_text(self.FRONTMATTER + body)
            result = validator("brief", str(brief), "--matt")
        self.assertEqual(result.returncode, 1)
        return result.stdout + result.stderr

    def test_a_missing_workflow_section_is_refused_with_every_required_field_and_the_template(self):
        out = self.refusal("")
        self.assertIn("e.g.:\n", out)
        example = out.split("e.g.:\n", 1)[1]
        for key in ("Methodology: matt", "Executor: kai", "Route: build", "Phase: implement", "Next gate:",
                    "Start:", "DDD: n/a:", "UX: n/a:", "Procedure: ~/.agents/skills/engineering-workflow/SKILL.md",
                    "Procedure: ~/.agents/skills/ask-matt/SKILL.md", "Loaded:"):
            self.assertIn(key, example)
        self.assertIn("engineering-workflow/references/phase-record.md", out)

    def test_two_workflow_sections_are_refused_as_two(self):
        self.assertIn("2 '## Workflow' sections; keep one",
                      self.refusal("\n## Workflow\nMethodology: matt\n\n## Workflow\nMethodology: matt\n"))


class BriefPinTeachingTests(StepFixture):
    """The pin is taught where a lead reads it, and the taught Check line is one the validator reads."""

    def test_the_phase_record_and_herdr_teach_the_pin_commands_and_the_stamp(self):
        for body in (PHASE_RECORD, HERDR):
            with self.subTest(body=body.name):
                text = prose(body)
                for needle in ("brief-digest", "brief=sha256:", "--brief-digest sha256:"):
                    self.assertIn(needle, text)

    def test_the_phase_record_says_what_the_pin_ignores_and_when_to_re_stamp(self):
        text = prose(PHASE_RECORD)
        self.assertIn("above its first `## Return` line", text)
        self.assertIn("`- [x]` or `- [X]` read as `- [ ]`", text)
        self.assertRegex(text, r"(?i)amend the brief yourself, run `brief-digest` again and stamp the new digest")
        self.assertRegex(text, r"(?i)without it `receipt` behaves as before")

    def test_the_taught_dispatch_check_line_with_a_pin_is_read_by_the_gate(self):
        line = taught(PHASE_RECORD, "Check: start implement").replace("<digest>", "a" * 64).replace(
            "<UTC>", "2026-10-17T10:00:00Z")
        self.assertIn("brief=sha256:" + "a" * 64, line)
        text = self.record(steps("Scope", "Grilling", pending=("Implement",)),
                           NO_BRANCH + " at:2026-10-17T09:00:00Z", phase="implement", extra=line + "\n")
        self.passes(text)


class ResearchChecklistTeachingTests(unittest.TestCase):
    """A lead that copies the taught research checklist gets one that stays valid as its phases are ticked."""

    def map_steps(self):
        found = re.search(r"(?m)^- research: (.+)$", WORKFLOW_MAP.read_text())
        self.assertTrue(found, "the workflow map lists no research steps")
        return [name.strip() for name in found.group(1).split(",")]

    def test_the_communication_guide_sends_a_brief_with_its_own_checklist_to_the_maps_steps(self):
        text = prose(COMMUNICATION)
        self.assertIn("A brief that keeps its own Phase checklist uses its route's step names in order from "
                      "[workflow-map.md](../../engineering-workflow/references/workflow-map.md) Required steps; "
                      "otherwise it points to the parent checklist with `State:`.", text)

    def test_the_phase_record_example_is_the_maps_research_steps_in_order(self):
        example = re.search(r"```text\n## Phase checklist\n(.*?)```", PHASE_RECORD.read_text(), re.S)
        self.assertTrue(example, "the phase record shows no example Phase checklist")
        labels = re.findall(r"(?m)^- \[[ x]\] ([A-Za-z-]+):", example.group(1))
        self.assertEqual([label.lower() for label in labels], self.map_steps())


class DoorbellTeachingTests(unittest.TestCase):
    """The four doorbell rules and the neutral launch sentence, as herdr.md teaches them."""

    def test_the_return_file_is_authoritative_and_the_lead_checks_for_it_whenever_it_wakes(self):
        text = prose(HERDR)
        self.assertIn("The file is authoritative; the ring is only a hint, so whenever you wake, and between your "
                      "own steps, check the expected return files whether or not a ring came.", text)

    def test_the_worker_runs_its_bounded_retry_in_the_foreground_and_never_sends_to_a_busy_lead(self):
        text = prose(HERDR)
        self.assertRegex(text, r"The worker runs the wait and every retry in the foreground, never as a background task")
        self.assertIn("It never sends to a busy lead, for any kind of lead.", text)

    def test_the_composer_rule_is_one_a_worker_can_meet(self):
        text = prose(HERDR)
        self.assertIn("read the composer; if it holds a draft or is unreadable, do not send", text)
        self.assertNotIn("verified layout", text)

    def test_the_launch_sentence_names_no_launcher_and_no_second_methodology(self):
        text = prose(HERDR)
        self.assertIn("Launch a fresh worker plainly: Mifal's Guide makes Matt the owner in every harness.", text)
        for gone in ("launcher", "another methodology", "fresh Claude worker", "owner contract", "advisory review"):
            self.assertNotIn(gone, text)


if __name__ == "__main__":
    unittest.main()
