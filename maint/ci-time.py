#!/usr/bin/env python3
"""Report a CI job's elapsed time against the timeout-minutes its workflow sets, with a warning from 75%.

    python3 maint/ci-time.py WORKFLOW JOB START END    START and END in epoch seconds

Each timed job stamps START in its first step and calls this from a last step that runs even after a failure.
A job that reaches its limit is cancelled, and a cancelled job may never get here: no report is not proof the job
had time to spare. Any unusable clock input, an oversized number included, and any failure to read WORKFLOW or the
job's limit there, is a warning, never a failed job.
"""
import re
import sys

WARN_PERCENT = 75


def limit_minutes(workflow, job):
    try:
        with open(workflow, encoding="utf-8") as f:
            text = f.read()
    except (OSError, ValueError):
        return None
    block = re.search(rf"(?ms)^  {re.escape(job)}:[ \t]*(?:#[^\n]*)?\n(.*?)(?=^  \S|\Z)", text)
    found = block and re.search(r"(?m)^    timeout-minutes: ([1-9][0-9]{0,5})[ \t]*(?:#.*)?$", block.group(1))
    return int(found.group(1)) if found else None


def main(argv):
    workflow, job, start, end = argv
    limit = limit_minutes(workflow, job)
    if limit is None:
        print(f"::warning title=Job time::{job}: no report, since its timeout-minutes couldn't be read from {workflow}.")
        return 0
    if not (re.fullmatch("[0-9]{1,18}", start) and re.fullmatch("[0-9]{1,18}", end)) or int(end) < int(start):
        print(f"::warning title=Job time::{job}: no elapsed time, since the clock input was start {start!r}, "
              f"end {end!r}. Its limit is {limit} minutes.")
        return 0
    elapsed = int(end) - int(start)
    percent = elapsed * 100 // (limit * 60)
    said = f"{job} ran {elapsed // 60}m {elapsed % 60}s of its {limit}-minute limit ({percent}%)"
    if elapsed * 100 >= limit * 60 * WARN_PERCENT:
        print(f"::warning title=Job time::{said}. At {limit} minutes GitHub cancels it, and a cancelled job "
              "may print no report.")
    else:
        print(said + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
