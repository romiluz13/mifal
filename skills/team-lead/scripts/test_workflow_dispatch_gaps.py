"""Gaps a live team hit on 2026-10-31, through the public validator CLI."""
import hashlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_workflow_cuts as cuts
from test_workflow_contracts import SCRIPT

POOL = Path.home() / ".agents" / "skills"
DECIDED = cuts.NO_BRANCH + " at:2026-10-17T09:00:00Z"
START_IMPLEMENT = "Check: start implement | passed | gate exit 0; dispatch 2 at:2026-10-17T10:00:00Z\n"


def body(name):
    return (POOL / name / "SKILL.md").resolve()


def selected(name, executor, at=None):
    path = body(name)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return (f"Procedure: {path}\nLoaded: {path} | {executor}: sha256:{digest} Skill tool load"
            + (f" at:{at}" if at else "") + "\n")


class ImplementStartTests(cuts.StepFixture):
    """The lead logged `Check: start implement` with neither its implement and tdd reads nor an exemption."""

    def lead(self, extra="", phase="research"):
        text = self.record(cuts.steps("Scope", "Grilling", pending=("Implement", "Review")), DECIDED, phase=phase)
        text = "\n".join(l for l in text.splitlines() if not any(str(p) in l for p in self.f.phase_skills)) + "\n"
        return text.replace("\n## Phase checklist", "\n" + extra + "\n## Phase checklist", 1)

    def test_a_start_implement_check_without_reads_or_exemption_is_refused(self):
        self.passes(self.lead())
        self.refused(self.lead(START_IMPLEMENT), "implement SKILL.md", "tdd SKILL.md")

    def test_the_leads_implement_and_tdd_reads_before_the_check_pass(self):
        reads = selected("implement", "worker", "2026-10-17T09:59:00Z") + selected("tdd", "worker", "2026-10-17T09:59:00Z")
        self.passes(self.lead(reads + START_IMPLEMENT))

    def test_reads_after_the_check_are_late(self):
        reads = selected("implement", "worker", "2026-10-17T10:30:00Z") + selected("tdd", "worker", "2026-10-17T10:30:00Z")
        self.refused(self.lead(reads + START_IMPLEMENT), "after the 2026-10-17T10:00:00Z start Check")

    def test_an_exemption_stamped_before_the_check_passes(self):
        self.passes(self.lead("Implement: n/a: docs-only: only the guide changes at:2026-10-17T09:59:00Z\n" + START_IMPLEMENT))

    def test_an_exemption_stamped_after_the_check_is_refused(self):
        self.refused(self.lead("Implement: n/a: docs-only: only the guide changes at:2026-10-17T10:30:00Z\n" + START_IMPLEMENT),
                     "Implement exemption is stamped 2026-10-17T10:30:00Z, after the 2026-10-17T10:00:00Z start Check")

    def test_an_unstamped_exemption_passes_with_a_note(self):
        result = self.passes(self.lead("Implement: n/a: docs-only: only the guide changes\n" + START_IMPLEMENT))
        self.assertIn("note: the Implement exemption has no at: time", result.stderr)

    def test_an_unstamped_start_check_still_brings_the_reads(self):
        self.refused(self.lead(START_IMPLEMENT.replace(" at:2026-10-17T10:00:00Z", "")),
                     "A 'Check: start' line of implement work needs implement SKILL.md")

    def test_the_message_names_the_step_that_started(self):
        remediate = START_IMPLEMENT.replace("start implement", "start remediate")
        self.refused(self.lead("Implement: n/a: docs-only: only the guide changes at:2026-10-17T10:30:00Z\n" + remediate),
                     "start Check of remediate")

    def test_a_cut_of_implement_lifts_it(self):
        self.passes(self.lead(f"Cut: implement | {cuts.HUMAN} | {cuts.SOURCE}\n" + START_IMPLEMENT))


class ImplementDispatchTests(cuts.StepFixture):
    """The gate that runs before an implement dispatch is `brief --matt`: it reads the lead's State."""

    def parent(self, extra=""):
        path = self.f.root / "lead-state.md"
        path.write_text("## Workflow\nExecutor: lead\nRoute: build\n" + extra +
                        "## Phase checklist\n- [x] Scope: asked\n- [x] Grilling: done\n- [ ] Implement\n- [ ] Report\n")
        return path

    def brief(self, parent, phase="implement"):
        text = self.record(cuts.steps("Scope"), phase=phase)
        text = "\n".join(l for l in text.splitlines() if not l.startswith("Route decision:")) + "\n"
        head, _, _ = text.partition("\n## Phase checklist")
        return self.f.brief() + f"{head}State: {parent}\n"

    def check(self, text):
        return self.f.run_check("brief", text, "--matt")

    def test_an_implement_brief_under_a_lead_with_neither_reads_nor_exemption_is_refused(self):
        result = self.check(self.brief(self.parent()))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("before dispatching implement work", result.stderr)

    def test_the_leads_coordination_exemption_passes(self):
        parent = self.parent("Implement: n/a: coordination: the worker owns the code\n")
        result = self.check(self.brief(parent))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_leads_own_implement_and_tdd_reads_pass(self):
        lines = "".join(l for l in (selected("implement", "lead") + selected("tdd", "lead")).splitlines(True)
                        if l.startswith("Loaded:"))
        result = self.check(self.brief(self.parent(lines)))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_another_executors_reads_do_not_count(self):
        lines = "".join(l for l in (selected("implement", "worker") + selected("tdd", "worker")).splitlines(True)
                        if l.startswith("Loaded:"))
        result = self.check(self.brief(self.parent(lines)))
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_a_standalone_implement_brief_passes_with_a_note(self):
        result = self.check(self.f.brief() + self.record(cuts.steps("Scope"), phase="implement"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("note: this implement brief names no State:", result.stderr)

    def test_a_lead_read_with_a_stale_digest_does_not_count(self):
        lines = "".join(re.sub(r"sha256:[0-9a-f]{64}", "sha256:" + "0" * 64, l)
                        for l in (selected("implement", "lead") + selected("tdd", "lead")).splitlines(True)
                        if l.startswith("Loaded:"))
        result = self.check(self.brief(self.parent(lines)))
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_a_remediate_brief_is_held_the_same_way(self):
        result = self.check(self.brief(self.parent(), phase="remediate"))
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_a_research_brief_is_not_held(self):
        result = self.check(self.brief(self.parent(), phase="research").replace(
            "\n".join(f"Procedure: {p}" for p in self.f.phase_skills[:2]), ""))
        self.assertEqual(result.returncode, 0, result.stderr)


class CorrectionIdTests(cuts.StepFixture):
    """A correction keeps `task: N` and adds `attempt: N.M`; the refusal must say so."""

    def test_an_attempt_id_in_the_task_field_names_the_attempt_field(self):
        text = self.f.brief().replace("task: 1\n", "task: 1.2\n")
        result = self.f.run_check("brief", text)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("keep 'task: 1' and add 'attempt: 1.2'", result.stderr)

    def test_the_task_and_attempt_form_passes(self):
        result = self.f.run_check("brief", self.f.brief().replace("task: 1\n", "task: 1\nattempt: 1.2\n"))
        self.assertEqual(result.returncode, 0, result.stderr)


class HiddenWorkflowLineTests(cuts.StepFixture):
    """A note heading placed between Workflow lines hid every later Check and Loaded line, without a word."""

    def test_workflow_lines_under_a_later_heading_are_refused(self):
        text = self.record(cuts.steps("Scope", "Grilling", pending=("Implement",)), phase="implement")
        head, _, tail = text.partition("\n## Phase checklist")
        hidden = head.replace("\nRoute decision:", "\n## 7 resolution\nThe owner settled it.\nRoute decision:", 1)
        self.refused(hidden + "\n## Phase checklist" + tail, "'## 7 resolution' hides")

    def test_a_bare_field_line_appended_under_the_checklist_is_refused(self):
        text = self.record(cuts.steps("Scope", "Grilling", pending=("Implement",)), phase="implement")
        self.refused(text + START_IMPLEMENT, "'## Phase checklist' hides")

    def test_a_commented_field_line_is_not_hidden_work(self):
        text = self.record(cuts.steps("Scope", "Grilling", pending=("Implement",)), phase="implement")
        self.passes(text + "\n## Notes\n<!-- Check: start implement | passed | draft -->\n")

    def test_prose_under_a_later_heading_passes(self):
        text = self.record(cuts.steps("Scope", "Grilling", pending=("Implement",)), phase="implement")
        self.passes(text + "\n## Notes\nThe owner settled it at 15:04Z; see decisions.md.\n")


class RetroHeadingTests(cuts.StepFixture):
    """`## Findings, most severe first` was refused as a missing Findings section."""

    def finished(self, report):
        self.f.retro_report.write_text(report)
        self.f.retro = ("Retro: sha256:" + hashlib.sha256(self.f.retro_report.read_bytes()).hexdigest() +
                        f" | {self.f.retro_report}\nCheck: retro | passed | current fixture session reviewed\n")
        return self.f.completed_workflow()

    def test_a_findings_heading_with_a_suffix_passes(self):
        self.passes(self.finished("## Sources\nThis session.\n## Findings, most severe first\n1. None needed.\n"), "accept")

    def test_a_missing_findings_section_is_still_refused(self):
        self.refused(self.finished("## Sources\nThis session.\n## Findingsless\nNone.\n"), "'## Findings'", gate="accept")


class ProcedureHalfTests(cuts.StepFixture):
    """A retro read was recorded, but its Procedure line was missing; the message must say which half."""

    def test_a_loaded_read_without_its_procedure_line_says_so(self):
        text = self.record(cuts.steps("Scope", "Grilling", "Implement", "Review"), phase="retro")
        retro = next(l for l in text.splitlines() if l.startswith("Procedure:") and "/retro/" in l)
        self.refused(text.replace(retro + "\n", ""), "has a Loaded line for retro SKILL.md but no 'Procedure:")

    def test_neither_half_names_both(self):
        text = self.record(cuts.steps("Scope", "Grilling", "Implement", "Review"), phase="retro")
        text = "\n".join(l for l in text.splitlines() if "/retro/" not in l) + "\n"
        self.refused(text, "needs retro SKILL.md: add 'Procedure:")


class StampTests(unittest.TestCase):
    """Check times typed by hand came out wrong; `stamp` appends the line with the real UTC time."""

    RECORD = "# Task\n## Workflow\nExecutor: lead\nCheck: start research | passed | gate at:2026-10-17T10:00:00Z\n\n## Notes\nprose\n"

    def run_stamp(self, text, value):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "record.md"
            path.write_text(text)
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), "stamp", str(path), value],
                                    capture_output=True, text=True)
            return result, path.read_text()

    def test_the_line_lands_last_in_the_workflow_section_with_a_utc_time(self):
        result, after = self.run_stamp(self.RECORD, "start implement | passed | brief 2.md --matt exit 0")
        self.assertEqual(result.returncode, 0, result.stderr)
        line = re.search(r"(?m)^Check: start implement \| passed \| brief 2\.md --matt exit 0 at:(\S+)$", after)
        self.assertIsNotNone(line, after)
        self.assertRegex(line.group(1), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertLess(after.index(line.group(0)), after.index("## Notes"))
        self.assertEqual(after.replace(line.group(0) + "\n", ""), self.RECORD)
        self.assertIn(line.group(0), result.stdout)

    def test_a_value_that_is_not_a_passed_check_is_refused(self):
        for value in ("start implement | failed | gate exit 1", "start implement", "start x | passed | e at:2026-10-17T10:00:00Z"):
            with self.subTest(value):
                result, after = self.run_stamp(self.RECORD, value)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(after, self.RECORD)

    def test_a_multiline_value_is_refused(self):
        result, after = self.run_stamp(self.RECORD, "start implement | passed | gate exit 0\nImplement: n/a: docs-only: x")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(after, self.RECORD)

    def test_crlf_line_endings_are_kept(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "record.md"
            path.write_bytes(self.RECORD.replace("\n", "\r\n").encode())
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), "stamp", str(path), "start review | passed | g"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = path.read_bytes()
            self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))
            self.assertIn(b"Check: start review | passed | g at:", data)

    def test_a_symlinked_record_is_written_through_the_link(self):
        with tempfile.TemporaryDirectory() as d:
            target, link = Path(d) / "record.md", Path(d) / "link.md"
            target.write_text(self.RECORD)
            link.symlink_to(target)
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), "stamp", str(link), "start review | passed | g"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(link.is_symlink())
            self.assertIn("Check: start review | passed | g at:", target.read_text())

    def test_an_unclosed_fence_is_refused(self):
        text = self.RECORD.replace("Executor: lead\n", "Executor: lead\n```\n")
        result, after = self.run_stamp(text, "start review | passed | g")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(after, text)

    def test_a_record_without_one_workflow_section_is_left_alone(self):
        result, after = self.run_stamp("# Task\n", "start implement | passed | gate exit 0")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(after, "# Task\n")


if __name__ == "__main__":
    unittest.main()
