"""The brief pin: `brief-digest` and `receipt --brief-digest`, through the public validator CLI."""
import hashlib
import subprocess
import sys
import unittest

import test_workflow_contracts as contracts
from test_workflow_cuts import StepFixture

RECEIPT = ("\n## Return\nCloses: 1\n### Result\nReviewed fixture.\n### Claims\n{claims}"
           "### Evidence\nReview trace.\n")
CLAIM = "- behavior: passed at the fixture digest\n"
SECOND = "- hard-claim: passed at the fixture digest\n"
BRIEF_SECOND = "- behavior: check the artifact.\n- hard-claim: run the hard check.\n"
AMENDMENT = "- amended-claim: run the amended check.\n"


class BriefPinTests(StepFixture):
    def dispatched(self):
        """The brief the lead writes: two Done-means claims and the Workflow record, no return yet."""
        return self.f.brief().replace("- behavior: check the artifact.\n", BRIEF_SECOND) + self.f.workflow()

    def returned(self, brief, claims=CLAIM + SECOND):
        return brief + RECEIPT.format(claims=claims) + self.f.load_lines()

    def pin(self, text):
        result = self.f.run_check("brief-digest", text)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"^sha256:[0-9a-f]{64}\n$")
        return result.stdout.strip()

    def receipt(self, text, pin=None):
        args = ("--matt",) + (("--brief-digest", pin) if pin else ())
        return self.f.run_check("receipt", text, *args)

    def refused(self, text, pin):
        result = self.receipt(text, pin)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("brief changed since it was pinned", result.stderr)
        self.assertIn(f"pinned {pin}", result.stderr)

    def test_the_digest_is_the_hash_of_the_text_above_the_first_return_with_ticks_unmarked(self):
        text = ("---\ntask: 1\n---\n## Why\nx\n- [x] Scope: asked\n- [X] Plan: made\n- [ ] Verify: pending\n"
                "## Return\nCloses: 1\n")
        region = "---\ntask: 1\n---\n## Why\nx\n- [ ] Scope: asked\n- [ ] Plan: made\n- [ ] Verify: pending\n"
        self.assertEqual(self.pin(text), "sha256:" + hashlib.sha256(region.encode()).hexdigest())

    def test_the_digest_ignores_ticks_the_return_line_endings_and_trailing_whitespace(self):
        brief = self.dispatched()
        base = self.pin(brief)
        ticked = brief.replace("- [ ] Implement:", "- [x] Implement:")
        self.assertNotEqual(ticked, brief)
        loud = ticked.replace("- [x] Implement:", "- [X] Implement:")
        for label, text in (("ticked", ticked), ("upper-case tick", loud),
                            ("returned", self.returned(ticked)),
                            ("crlf", brief.replace("\n", "\r\n")),
                            ("trailing spaces", brief.replace("## Outcome\n", "## Outcome   \n"))):
            with self.subTest(label):
                self.assertEqual(self.pin(text), base)

    def test_any_other_edit_changes_the_digest(self):
        brief = self.dispatched()
        base = self.pin(brief)
        edits = {
            "outcome": brief.replace("Evidence-backed review.", "Anything goes."),
            "claim cut": brief.replace(BRIEF_SECOND, "- behavior: check the artifact.\n"),
            "checklist line removed": brief.replace("- [ ] Implement: behavior test must pass\n", ""),
            "checklist line renamed": brief.replace("- [ ] Implement:", "- [ ] Implementation:"),
            "tick on a non-list line": brief.replace("## Stop rule\nOne pass.", "## Stop rule\nOne pass. [x]"),
        }
        for label, text in edits.items():
            with self.subTest(label):
                self.assertNotEqual(self.pin(text), base)

    def test_a_fenced_return_line_is_not_the_boundary(self):
        fenced = ("---\ntask: 1\n---\n## Why\nWrite the answer under:\n```\n## Return — attempt 1\n```\n"
                  "## Outcome\nOne answer.\n## Return\nCloses: 1\n")
        edited = fenced.replace("One answer.", "Two answers.")
        self.assertNotEqual(self.pin(fenced), self.pin(edited))

    def test_an_unclosed_fence_that_hides_the_boundary_is_refused(self):
        result = self.f.run_check("brief-digest", "---\ntask: 1\n---\n## Why\n```\nopen\n## Return\nCloses: 1\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("unclosed fence", result.stderr)

    def test_a_missing_file_is_a_usage_error(self):
        absent = self.f.root / "absent.md"
        result = subprocess.run([sys.executable, "-B", str(contracts.SCRIPT), "brief-digest", str(absent)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_a_cut_done_means_claim_passes_without_the_pin_and_is_refused_with_it(self):
        brief = self.dispatched()
        pin = self.pin(brief)
        cut = self.returned(brief.replace(BRIEF_SECOND, "- behavior: check the artifact.\n"), CLAIM)
        without = self.receipt(cut)
        self.assertEqual(without.returncode, 0, without.stderr)
        self.refused(cut, pin)

    def test_an_edited_outcome_passes_without_the_pin_and_is_refused_with_it(self):
        brief = self.dispatched()
        pin = self.pin(brief)
        edited = self.returned(brief.replace("Evidence-backed review.", "Whatever the worker found easiest."))
        without = self.receipt(edited)
        self.assertEqual(without.returncode, 0, without.stderr)
        self.refused(edited, pin)

    def test_ticks_only_pass_with_the_pin(self):
        brief = self.dispatched()
        pin = self.pin(brief)
        ticked = self.returned(brief.replace("- [ ] Implement:", "- [x] Implement:"))
        result = self.receipt(ticked, pin)
        self.assertEqual(result.returncode, 0, result.stderr)
        unticked = self.receipt(self.returned(brief), pin)
        self.assertEqual(unticked.returncode, 0, unticked.stderr)

    def test_an_amendment_passes_once_the_lead_re_stamps_and_not_before(self):
        brief = self.dispatched()
        old = self.pin(brief)
        amended = brief.replace(BRIEF_SECOND, BRIEF_SECOND + AMENDMENT)
        new = self.pin(amended)
        self.assertNotEqual(new, old)
        text = self.returned(amended, CLAIM + SECOND + AMENDMENT.replace("run the amended check.", "passed at the fixture digest"))
        self.refused(text, old)
        result = self.receipt(text, new)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_pin_is_checked_whether_or_not_matt_mode_is_asked_for(self):
        brief = self.dispatched()
        pin = self.pin(brief)
        edited = self.returned(brief.replace("Evidence-backed review.", "Anything goes."))
        result = self.f.run_check("receipt", edited, "--brief-digest", pin)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("brief changed since it was pinned", result.stderr)

    def test_a_malformed_pin_is_a_usage_error_and_the_other_commands_do_not_take_one(self):
        text = self.returned(self.dispatched())
        for bad in ("abc", "sha256:abc", "sha256:" + "g" * 64, "md5:" + "a" * 32):
            with self.subTest(pin=bad):
                result = self.receipt(text, bad)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("sha256", result.stderr)
        result = self.f.run_check("brief", text, "--brief-digest", "sha256:" + "a" * 64)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_without_the_flag_a_receipt_is_checked_as_before(self):
        result = self.receipt(self.returned(self.dispatched()))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("pinned", result.stderr)


if __name__ == "__main__":
    unittest.main()
