import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import PYTHON, REPO

SCRIPT = REPO / "maint" / "ci-time.py"
TIMED = {".github/workflows/test.yml": ("mifal", "shipped"), ".github/workflows/release.yml": ("release",)}
FIXTURE = """name: t
jobs:
  first:
    runs-on: macos-latest
    timeout-minutes: 40
    steps:
      - run: echo "timeout-minutes: 5"
  second:
    timeout-minutes: 20
    steps: []
  untimed:
    steps: []
  commented:  # a job line with a comment
    timeout-minutes: 30  # half an hour
  zero:
    timeout-minutes: 0
"""


def job_block(text, job):
    return re.search(rf"(?ms)^  {job}:\n(.*?)(?=^  \S|\Z)", text).group(1)


class Report(unittest.TestCase):
    """Each timed job reports its elapsed time against the limit its workflow sets, and warns from 75%."""

    def setUp(self):
        self.workflow = Path(tempfile.mkdtemp(prefix="mifal-ci-time-")) / "w.yml"
        self.addCleanup(lambda: (self.workflow.unlink(), self.workflow.parent.rmdir()))
        self.workflow.write_text(FIXTURE)

    def report(self, job, start, end, workflow=None):
        return subprocess.run([PYTHON, "-B", str(SCRIPT), str(workflow or self.workflow), job, str(start), str(end)],
                              capture_output=True, text=True, timeout=60)

    def test_below_75_percent_reports_without_a_warning(self):
        result = self.report("first", 1000, 1000 + 40 * 60 * 3 // 4 - 1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("first ran 29m 59s of its 40-minute limit (74%)", result.stdout)
        self.assertNotIn("::warning", result.stdout)

    def test_at_75_percent_warns(self):
        result = self.report("first", 1000, 1000 + 40 * 60 * 3 // 4)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"(?m)^::warning title=Job time::first ran 30m 0s of its 40-minute limit "
                                        r"\(75%\)\. At 40 minutes GitHub cancels it")

    def test_above_75_percent_warns(self):
        result = self.report("second", 0, 19 * 60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::warning title=Job time::second ran 19m 0s of its 20-minute limit (95%)", result.stdout)

    def test_each_job_reads_its_own_limit(self):
        self.assertIn("of its 20-minute limit", self.report("second", 0, 60).stdout)
        self.assertIn("of its 40-minute limit", self.report("first", 0, 60).stdout)

    def test_bad_clock_input_warns_and_does_not_fail_the_job(self):
        for start, end in (("", 100), ("abc", 100), (100, ""), (100, 99), ("-5", 100), ("1e3", 2000), ("\u00b2", 100),
                           ("1" * 5000, "2" * 5000)):
            with self.subTest(start=str(start)[:20], end=str(end)[:20]):
                result = self.report("first", start, end)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertRegex(result.stdout, r"(?m)^::warning title=Job time::first: no elapsed time")
                self.assertNotIn("Traceback", result.stderr)

    def test_yaml_comments_do_not_hide_a_limit(self):
        result = self.report("commented", 0, 60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("of its 30-minute limit", result.stdout)

    def test_a_missing_limit_or_workflow_warns_and_does_not_fail_the_job(self):
        for job, workflow in (("untimed", None), ("missing", None), ("zero", None),
                              ("first", self.workflow.parent / "absent.yml"), ("first", self.workflow.parent)):
            with self.subTest(job=job, workflow=workflow):
                result = self.report(job, 0, 60, workflow)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertRegex(result.stdout, rf"(?m)^::warning title=Job time::{job}: no report, since ")
                self.assertNotIn("Traceback", result.stderr)


class Workflows(unittest.TestCase):
    """The report is wired into every timed job: stamped first, reported last even after a failed step."""

    def test_every_timed_job_stamps_its_start_and_reports_last_even_after_a_failure(self):
        for workflow, jobs in TIMED.items():
            text = (REPO / workflow).read_text()
            self.assertEqual(sorted(re.findall(r"(?m)^  ([\w-]+):\n(?:    .*\n)*?    timeout-minutes:", text)),
                             sorted(jobs), workflow)
            for job in jobs:
                with self.subTest(workflow=workflow, job=job):
                    steps = job_block(text, job).split("\n      - ")[1:]
                    self.assertIn('echo "MIFAL_JOB_START=$(date +%s)" >> "$GITHUB_ENV"', steps[0])
                    self.assertIn("if: always()", steps[-1])
                    self.assertIn(f'python3 maint/ci-time.py {workflow} "$GITHUB_JOB" "${{MIFAL_JOB_START:-}}" '
                                  '"$(date +%s)"', steps[-1])

    def test_timing_can_never_fail_a_job(self):
        for workflow, jobs in TIMED.items():
            for job in jobs:
                with self.subTest(workflow=workflow, job=job):
                    steps = job_block((REPO / workflow).read_text(), job).split("\n      - ")[1:]
                    for step in (steps[0], steps[-1]):
                        self.assertRegex(step, r"(?m)^        continue-on-error: true$", step)

    def test_the_report_runs_from_the_workflow_s_own_commands_after_a_failed_step(self):
        for workflow, jobs in TIMED.items():
            for job in jobs:
                with self.subTest(workflow=workflow, job=job):
                    steps = job_block((REPO / workflow).read_text(), job).split("\n      - ")[1:]
                    command = lambda step: re.search(r"(?m)^ *run: (.*)$", step).group(1)
                    with tempfile.TemporaryDirectory() as tmp:
                        env_file = Path(tmp) / "env"
                        env = {"PATH": "/usr/bin:/bin", "GITHUB_ENV": str(env_file), "GITHUB_JOB": job}
                        subprocess.run(["/bin/bash", "-eo", "pipefail", "-c", command(steps[0])], env=env,
                                       cwd=REPO, check=True)
                        failed = subprocess.run(["/bin/bash", "-c", "exit 1"], env=env)
                        self.assertEqual(failed.returncode, 1)
                        env.update(line.split("=", 1) for line in env_file.read_text().splitlines())
                        env["PATH"] = f"{Path(PYTHON).parent}:/usr/bin:/bin"
                        result = subprocess.run(["/bin/bash", "-eo", "pipefail", "-c", command(steps[-1])], env=env,
                                                cwd=REPO, capture_output=True, text=True, timeout=60)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertRegex(result.stdout, rf"^{job} ran 0m \d+s of its \d+-minute limit \(0%\)\.$")

    def test_the_report_takes_each_limit_from_its_workflow(self):
        for workflow, jobs in TIMED.items():
            for job in jobs:
                with self.subTest(workflow=workflow, job=job):
                    limit = re.search(r"(?m)^    timeout-minutes: (\d+)$", job_block((REPO / workflow).read_text(),
                                                                                    job)).group(1)
                    result = subprocess.run([PYTHON, "-B", str(SCRIPT), str(REPO / workflow), job, "0", "60"],
                                            capture_output=True, text=True, timeout=60)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(f"of its {limit}-minute limit", result.stdout)


if __name__ == "__main__":
    unittest.main()
