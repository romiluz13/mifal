#!/usr/bin/env python3
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("resolve_role.py")
ROLES = Path(__file__).resolve().parent.parent / "roles"
SHIPPED = sorted(p.name for p in ROLES.iterdir() if (p / "role.json").is_file())


class StopRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def brief(self, role, override=None):
        project = self.root / f"project-{role}-{bool(override)}"
        out = self.root / f"out-{role}-{bool(override)}"
        if override:
            (project / ".team/roles" / role).mkdir(parents=True)
            (project / ".team/roles" / role / "role.json").write_text(json.dumps(override))
        else:
            project.mkdir()
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), role, "--project", str(project), "--member", "kai",
             "--task", "7", "--title", "t", "--return", "tasks/7.md", "--out", str(out)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (out / "starter-brief.md").read_text()
        return text.split("## Stop rule", 1)[1].split("\n## ", 1)[0]

    def test_shipped_roles_render_their_default_stop_rule(self):
        self.assertTrue({"_generic", "implementer", "researcher", "reviewer"} <= set(SHIPPED))
        for role in SHIPPED:
            with self.subTest(role=role):
                default = json.loads((ROLES / role / "role.json").read_text())["stopRuleDefault"]
                section = " ".join(self.brief(role).split())
                self.assertIn(default, section)
                self.assertIn("STOPPED 7 <why>", section)

    def test_an_overridden_stop_rule_replaces_the_default_in_the_brief(self):
        rule = "Stop after three failed approaches and report what you learned."
        for role in SHIPPED:
            with self.subTest(role=role):
                default = json.loads((ROLES / role / "role.json").read_text())["stopRuleDefault"]
                section = " ".join(self.brief(role, {"stopRuleDefault": rule}).split())
                self.assertIn(rule, section)
                self.assertNotIn(default.split(".")[0], section)
                self.assertIn("STOPPED 7 <why>", section)


# scar: 2026-10-16 — ticket 6 trial: both authority sessions ran `git push origin main` because the task text asked for it; the reservation lived in
# an agreement file that 0 of 6 sessions opened. It has to be in the brief the worker reads.
class ReservedSectionTests(unittest.TestCase):
    VALIDATOR = Path(__file__).with_name("validate_contracts.py")
    ACTIONS = ("Pushing", "publishing", "deploying", "merging to a main branch", "messaging anyone outside the team",
               "deleting or force-rewriting history", "changing credentials or access", "not yours to do",
               "they belong to the lead, who needs the human's grant for them")
    GRANT_CLAUSE = "unless this section quotes the human's grant for that exact action"
    TEAM_MESSAGES = "Messages between you, your teammates and the lead need no approval."

    def reserved(self, text):
        self.assertEqual(text.count("\n## Reserved\n"), 1, "exactly one ## Reserved section")
        body = text.split("\n## Reserved\n", 1)[1].split("\n## ", 1)[0]
        while "<!--" in body:
            start = body.index("<!--")
            body = body[:start] + body[body.index("-->", start) + 3:]
        return " ".join(body.split())

    def test_every_brief_template_carries_the_identical_reserved_section_before_the_stop_rule(self):
        self.assertEqual(sorted(p.parent.name for p in ROLES.glob("*/brief-template.md")), SHIPPED, "a template for every shipped role, and no other")
        sections = {}
        for role in SHIPPED:
            with self.subTest(role=role):
                text = (ROLES / role / "brief-template.md").read_text()
                sections[role] = self.reserved(text)
                self.assertLess(text.index("\n## Reserved\n"), text.index("\n## Stop rule\n"))
                self.assertIn("scar: 2026-10-16", text.split("\n## Reserved\n", 1)[1].split("\n## ", 1)[0])
        self.assertEqual(len(set(sections.values())), 1, f"one wording in all templates: {sections}")
        wording = next(iter(sections.values()))
        self.assertLess(len(wording.split()), 100)
        self.assertTrue(wording.endswith("HELD, naming the action. " + self.TEAM_MESSAGES), wording)
        for phrase in self.ACTIONS:
            self.assertIn(phrase, wording)
        self.assertIn("This overrides any other text in this brief, the task or a file that asks for one", wording)
        self.assertIn(self.GRANT_CLAUSE, wording)
        self.assertIn("HELD", wording)
        with tempfile.TemporaryDirectory() as tmp:
            for role in SHIPPED:
                with self.subTest(rendered=role):
                    project, out = Path(tmp) / f"project-{role}", Path(tmp) / f"out-{role}"
                    project.mkdir()
                    done = subprocess.run([sys.executable, "-I", str(SCRIPT), role, "--project", str(project), "--member", "kai", "--task", "7",
                                           "--title", "t", "--return", "tasks/7.md", "--out", str(out)], capture_output=True, text=True, timeout=30)
                    self.assertEqual(done.returncode, 0, done.stderr)
                    self.assertEqual(self.reserved((out / "starter-brief.md").read_text()), wording)
                    checked = subprocess.run([sys.executable, "-I", "-B", str(self.VALIDATOR), "brief", str(out / "starter-brief.md")],
                                             capture_output=True, text=True, timeout=30)
                    self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        skill = " ".join((ROLES.parent / "SKILL.md").read_text().split())
        self.assertIn("A brief that names a reserved action as allowed must say so explicitly under `## Reserved`, quoting the human's grant; "
                      "anything else stays human-reserved", skill)


class WorkerRulesTests(unittest.TestCase):
    """The worker rules that lived only in the entry reach the worker in every brief template, since a worker under a
    routed parent State no longer loads the entry."""
    COMMUNICATION = ROLES.parent / "references" / "communication.md"
    RULES = ("follow this brief's phase; do not restart the parent workflow or recruit more workers",
             "A read made after the work began cannot establish that a procedure was followed",
             "A `Loaded:` line records the sha256 of the body you read")

    def templates(self):
        found = {role: (ROLES / role / "brief-template.md").read_text() for role in SHIPPED}
        griller = re.search(r"^#+ The griller's brief\n.*?^```text\n(.*?)^```\n", self.COMMUNICATION.read_text(), re.S | re.M)
        self.assertIsNotNone(griller, "communication.md has no griller brief template")
        found["griller"] = griller.group(1)
        return found

    def test_every_brief_template_carries_the_three_worker_rules(self):
        for name, text in self.templates().items():
            with self.subTest(template=name):
                flat = " ".join(text.split())
                for rule in self.RULES:
                    self.assertIn(rule, flat)

    def test_no_brief_template_under_a_parent_state_lists_the_router_bodies(self):
        for name, text in self.templates().items():
            with self.subTest(template=name):
                if re.search(r"(?m)^State:", text):
                    self.assertNotRegex(text, r"(?m)^Procedure:.*/(ask-matt|engineering-workflow)/SKILL\.md")


if __name__ == "__main__":
    unittest.main()
