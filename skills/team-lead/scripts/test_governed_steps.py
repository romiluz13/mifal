"""A body whose map row names no start step of the build route is held to the step it governs, not the record's phase."""
# scar: 2026-10-22 — a receipt was refused for a writing-for-agents read made at the retro step, held instead to the
# implement start; its ddd-scope and ddd-ground reads were left unordered.
import hashlib
from pathlib import Path
import unittest

import test_workflow_aliases as aliases

POOL = Path.home() / ".agents" / "skills"
START_IMPLEMENT = aliases.START_IMPLEMENT
START_RETRO = "Check: start retro | passed | gate exit 0 at:2026-10-17T13:00:00Z\n"
BEFORE_IMPLEMENT, BETWEEN, AFTER_RETRO = "2026-10-17T09:30:00Z", "2026-10-17T11:00:00Z", "2026-10-17T14:00:00Z"


class GovernedStepTests(aliases.AliasTimingTests):
    def with_read(self, name, at, checks, phase="implement"):
        body = POOL / name / "SKILL.md"
        digest = hashlib.sha256(body.read_bytes()).hexdigest()
        text = self.base(checks, phase=phase)
        old, _ = self.canonical_line(BEFORE_IMPLEMENT)
        return text.replace(old, f"{old}\nLoaded: {body} | worker: sha256:{digest} read event fixture-{name} at:{at}")

    def refused_for(self, kind, text, name, step):
        result = self.verdict(kind, text)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(f"{name}/SKILL.md", result.stderr)
        self.assertIn(f"'{step}'", result.stderr)

    def test_writing_for_agents_read_after_implement_and_before_retro_passes(self):
        for kind in ("workflow", "receipt"):
            with self.subTest(kind):
                self.passes(kind, self.with_read("writing-for-agents", BETWEEN, START_IMPLEMENT + START_RETRO))

    def test_writing_for_agents_read_after_the_retro_start_is_refused(self):
        for kind in ("workflow", "receipt"):
            with self.subTest(kind):
                self.refused_for(kind, self.with_read("writing-for-agents", AFTER_RETRO, START_IMPLEMENT + START_RETRO),
                                 "writing-for-agents", "retro")

    def test_ddd_scope_and_ground_are_held_to_the_implement_start(self):
        for name in ("ddd-scope", "ddd-ground"):
            for kind in ("workflow", "receipt"):
                with self.subTest(name=name, kind=kind):
                    self.passes(kind, self.with_read(name, BEFORE_IMPLEMENT, START_IMPLEMENT, phase="review"))
                    self.refused_for(kind, self.with_read(name, BETWEEN, START_IMPLEMENT, phase="review"),
                                     name, "implement")


if __name__ == "__main__":
    unittest.main()
