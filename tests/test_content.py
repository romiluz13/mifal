import codecs
import fnmatch
import hashlib
import importlib.util
import json
import re
import subprocess
import unittest

from support import REPO

# The shipped set, plan D9: the 27 Ask Matt skills, the local attachments, the factory core and herdr.
ASK_MATT = (
    "ask-matt", "grill-with-docs", "grill-me", "grilling", "domain-modeling", "prototype", "handoff", "to-spec",
    "to-tickets", "implement", "implement-spec", "tdd", "code-review", "pr", "retro", "triage", "diagnosing-bugs",
    "wayfinder", "improve-codebase-architecture", "codebase-design", "research", "to-questionnaire", "wizard",
    "wait-what", "teach", "writing-for-agents", "setup-matt-pocock-skills")
SHIPPED = set(ASK_MATT) | {
    "receiving-code-review", "ddd", "ddd-scope", "ddd-ground", "ddd-verify", "frontend-design", "agent-browser",
    "engineering-workflow", "team-lead", "setup-pre-commit", "verification-before-completion", "herdr"}
# Skills that exist elsewhere and do not ship; a shipped body must not depend on them.
UNSHIPPED = (
    "cloudflare", "codebase-hygiene", "commit", "compact-safe", "deploy-to-vercel", "diff-driven-docs",
    "find-skills", "github", "last30days", "mongodb-atlas-stream-processing", "mongodb-connection",
    "mongodb-mcp-setup", "mongodb-natural-language-querying", "mongodb-query-optimizer", "mongodb-schema-design",
    "mongodb-search-and-ai", "octocode", "security-review", "vercel-cli-with-tokens", "vercel-optimize",
    "writing-awesome-readmes", "design-accessibility-audit", "ddd-book", "ddd-exception")
# Optional integrations and path rules that name an unshipped skill on purpose (task 2 N2).
ALLOWED = {
    ("skills/ddd/SKILL.md", "ddd-book"): "optional integration, used only on explicit request",
    ("skills/ddd/SKILL.md", "ddd-exception"): "optional integration, used only on explicit request",
    ("skills/team-lead/references/review-routing.md", "security-review"): "a self-policy path rule, not a dependency",
}
# Shipped-set names that are not skill folders, plan D9.
SHIPPED_PATHS = {
    "herdr-adapter": "tools/herdr_adapter",
    "validate-contracts": "skills/team-lead/scripts/validate_contracts.py",
}
LEFT_OUT = (
    "skills/team-lead/recruitment/pitches", "skills/team-lead/recruitment/onboarded",
    "skills/team-lead/recruitment/examples", "skills/team-lead/recruitment/demo.sh",
    "skills/team-lead/recruitment/gaps.md", "skills/team-lead/scripts/test_demo.py")
LINK = re.compile(r"\]\(([^)\s]+)\)")
FENCE = re.compile(r"(?ms)^```.*?^```")
# The engine's own folders; the factory's private ones do not exist on a Mifal machine.
UNSHIPPED_PATHS = re.compile(r"\.agents/(scripts|tools)\b")
# Personal identifiers, kept as sha256 prefixes so this file does not ship them: the author's name and
# handle, private projects, profile and launcher names, the factory's owner variable, a private brief and tool.
DENIED = {
    "1a0806c20104d346", "776f49007a01981a", "7ff8d3807b844b13", "e5253ccc111e7310", "dd4bc119ea05e489",
    "84138e3e9c86337d", "9daa7e32e4afe10a", "0c46c1c0dcb05434", "515f6ce2a28a11a1", "6b39a32839317b67",
    "040fce9abddf536b", "35bc2a33cb1d075d",
}
# The author's name and handle may appear only on a credit line of a credit file, and in the project's own
# repository URL where a user is told how to clone it. The project's own repository and website URLs may
# appear in any file: they are how a reader reaches the project, and they name no folder on anyone's machine.
# Only the complete https URLs of this owner's mifal repository and site qualify, so a path, another
# repository or a lookalike host still counts as a leak. The owner is the one the README tells users to clone.
OWNER = re.search(r"git clone https://github\.com/([\w-]+)/mifal\.git", (REPO / "README.md").read_text()).group(1)
PROJECT_URL = re.compile(r"(?<![\w.@/-])https://(?:github\.com/" + re.escape(OWNER) + r"/mifal|"
                         + re.escape(OWNER) + r"\.github\.io/mifal)(?=\.git(?![\w.-])|[/#?]|[^\w.-]|$)")
CREDIT_TOKENS = {"1a0806c20104d346", "776f49007a01981a", "7ff8d3807b844b13"}
CREDIT_FILES = {"LICENSE", "NOTICE", "third_party/provenance.json", "skills/team-lead/SKILL.md",
                "lib/mifal/update.py", "README.md"}
CREDIT_LINE = re.compile(r'Copyright|"copyright"|^\s*author:|github\.com/|"repo":')
TOKEN = re.compile(r"[a-z0-9_-]+")
# Shipped by plan D9 but not rows of the workflow map: the implementer role names one, the lead uses the other.
OUTSIDE_THE_MAP = {"verification-before-completion", "herdr"}


def tracked():
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True, check=True).stdout
    return sorted(p for p in out.splitlines() if (REPO / p).is_file())


def prose():
    """Shipped Markdown, without test fixtures, which are data and may be broken on purpose."""
    return [p for p in tracked() if p.endswith(".md") and "/fixtures/" not in p]


def validator():
    spec = importlib.util.spec_from_file_location("validate_contracts",
                                                  REPO / SHIPPED_PATHS["validate-contracts"])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ShippedSet(unittest.TestCase):
    def test_exactly_the_planned_skills_ship(self):
        folders = {p.name for p in (REPO / "skills").iterdir() if p.is_dir() and p.name != "__pycache__"}
        self.assertEqual(folders, SHIPPED)
        self.assertEqual(len(folders), 39)

    def test_left_out_parts_of_team_lead_are_absent(self):
        self.assertEqual([p for p in LEFT_OUT if (REPO / p).exists()], [])

    def test_every_shipped_set_name_has_a_path(self):
        names = [n for _, _, column, _, shipped in validator().WORKFLOW_MAP_TABLES if column == "Skill"
                 for n in shipped]
        missing = [n for n in names if not (REPO / SHIPPED_PATHS.get(n, "skills/" + n)).exists()]
        self.assertEqual(missing, [])
        self.assertEqual(set(names) - set(SHIPPED_PATHS), SHIPPED - OUTSIDE_THE_MAP)

    def test_the_workflow_map_matches_the_shipped_set(self):
        v = validator()
        self.assertEqual(v.workflow_map_errors(REPO / "skills", lambda p: p.read_text(encoding="utf-8")), [])


class Loading(unittest.TestCase):
    """Claude Code re-attaches skills loaded through its Skill tool after compaction, up to about 5k tokens each;
    a file read is not re-attached."""

    def test_the_guide_loads_the_engineering_workflow_natively_first(self):
        text = (REPO / "guide/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("load the `engineering-workflow` skill completely", text)
        self.assertIn("native skill tool", text)
        self.assertNotIn("read `~/.agents/skills/engineering-workflow/SKILL.md` completely", text)

    def test_the_guide_keeps_secrets_out_of_the_transcript(self):
        self.assertIn("Keep secrets out of the transcript", (REPO / "guide/AGENTS.md").read_text(encoding="utf-8"))

    def test_the_engineering_workflow_loads_ask_matt_and_team_lead_natively_first(self):
        text = (REPO / "skills/engineering-workflow/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Load the `ask-matt` skill completely, as step 4 loads a skill", text)
        self.assertIn("load the `team-lead` skill completely the same way", text)
        self.assertIn("Prefer the native skill tool", text)
        self.assertIn("load `ddd` and the relevant phase procedure as step 4 loads a skill", text)
        self.assertIn("Load `setup-matt-pocock-skills` when needed", text)

    def test_the_ddd_phase_skills_load_ddd_natively_first(self):
        for name in ("ddd-scope", "ddd-ground", "ddd-verify"):
            with self.subTest(skill=name):
                text = " ".join((REPO / "skills" / name / "SKILL.md").read_text(encoding="utf-8").split())
                self.assertIn("Load the `ddd` skill completely, through your native skill tool", text)

    def test_team_leads_hard_lines_survive_a_truncated_reattach(self):
        text = (REPO / "skills/team-lead/SKILL.md").read_text(encoding="utf-8")
        start = text.index("\n## Hard lines\n")
        end = text.find("\n## ", start + 1)
        self.assertLess(end if end > 0 else len(text), 8000)
        head = " ".join(text[start:end].split())
        for rule in ("After a compaction, reload team-lead", "--gate entry|review|accept", "brief <brief> --matt",
                     "Pane checks before every prompt", "references/herdr.md", "Review only settled work",
                     "One writer per shared artifact"):
            with self.subTest(rule=rule):
                self.assertIn(rule, head)

    def test_a_refused_ring_is_retried_and_never_sent_to_a_busy_lead(self):
        def flat(rel):
            return " ".join((REPO / "skills/team-lead" / rel).read_text(encoding="utf-8").split())
        herdr = flat("references/herdr.md")
        for rule in ("Prompt only a teammate that is `idle` or `done`.", "`agent_blocked`",
                     "every 2 minutes for up to 30 minutes", "never sends to a busy lead"):
            with self.subTest(rule=rule):
                self.assertTrue(rule in herdr, f"references/herdr.md lacks: {rule}")
        for rel in ["references/herdr.md", "references/communication.md"] + sorted(
                str(p.relative_to(REPO / "skills/team-lead")) for p in (REPO / "skills/team-lead/roles").rglob("DOORBELL.md")):
            text = flat(rel)
            for dropped in ("skips the ring", "skip it if the lead isn't ready", "isn't ready within a bounded wait"):
                with self.subTest(file=rel, dropped=dropped):
                    self.assertFalse(dropped in text, f"{rel} still drops the ring: {dropped}")


class SoloEntry(unittest.TestCase):
    """String contracts: they show the instruction text is present, not that any agent follows it."""
    QUESTION = "Full workflow or cut? Recommended: full workflow."
    CHOICE_B = "Full workflow; no steps cut."

    def guide(self):
        return (REPO / "guide/AGENTS.md").read_text(encoding="utf-8")

    def workflow(self):
        return (REPO / "skills/engineering-workflow/SKILL.md").read_text(encoding="utf-8")

    def test_the_guide_asks_for_the_entry_line_the_checklist_and_the_question_before_the_first_edit(self):
        text = " ".join(self.guide().split())
        self.assertIn("before the first edit or dispatch", text)
        self.assertIn("Owner: Matt | Route: ROUTE | Phase: PHASE | Next gate: EVIDENCE", text)
        self.assertIn("phase checklist", text)
        self.assertIn(self.QUESTION, text)
        self.assertRegex(text, r"plain-text message that ends (the|your) turn, never through a user-input tool")

    def test_the_guide_names_the_skill_that_requires_the_question_and_who_asks_it(self):
        text = " ".join(self.guide().split())
        self.assertRegex(text, r"requirement of the `engineering-workflow` skill")
        self.assertIn("name that skill and quote its rule", text)
        self.assertIn("a briefed worker follows its brief", text)
        self.assertIn("no one to answer", text)
        self.assertIn("is not a cut", text)
        self.assertIn("`Cut: <steps> | <quote> | <source>`", text)
        self.assertNotIn("Cut: none", text)

    def test_the_guide_says_loading_is_not_doing_and_loads_one_skill_per_call(self):
        text = " ".join(self.guide().split())
        self.assertIn("loading a skill is not doing its step", text.lower())
        self.assertIn("red run before the fix", text)
        self.assertIn("one per call", text)
        self.assertIn("truncated skill read", text)

    def test_the_guide_stays_under_codexs_32_kib_cap(self):
        self.assertLess(len(self.guide().encode("utf-8")), 32 * 1024)

    def test_the_guide_does_not_claim_to_make_an_agent_perform_the_steps(self):
        text = self.guide().lower()
        for claim in ("guarantee", "enforce", "makes sure"):
            self.assertNotIn(claim, text)

    def test_the_debug_row_loads_tdd_for_every_behavioural_fix(self):
        row = next(l for l in self.workflow().splitlines() if l.startswith("| Debug |"))
        self.assertIn("tdd", row)
        self.assertIn("code-review", row)
        self.assertIn("existing failing test", row)
        self.assertIn("diagnosis-only", row)

    def test_the_solo_form_carries_the_entry_the_self_review_and_the_retro(self):
        text = " ".join(self.workflow().split())
        self.assertIn("**Solo form.**", text)
        form = text.split("**Solo form.**", 1)[1].split("- Complete a phase only when", 1)[0]
        for needle in (self.QUESTION, "no further stops", "review-snapshot.py", "self-review", "independent review",
                       "`retro`", "`writing-for-agents`", "before the final answer"):
            with self.subTest(needle=needle):
                self.assertIn(needle, form)

    def test_the_ordered_phases_paragraph_keeps_the_question_and_adds_the_recommended_answer(self):
        text = " ".join(self.workflow().split())
        self.assertIn('ask "full workflow or cut?"', text)
        self.assertIn("recommended answer", text.split("silence is not a cut", 1)[0].split("Only the human cuts", 1)[1])
        self.assertIn("silence is not a cut", text)

    def test_every_text_that_teaches_the_question_keeps_it_and_none_carries_the_unchosen_line(self):
        for rel in ("README.md", "guide/AGENTS.md", "skills/engineering-workflow/SKILL.md", "skills/team-lead/SKILL.md"):
            text = " ".join((REPO / rel).read_text(encoding="utf-8").split())
            with self.subTest(file=rel):
                self.assertRegex(text, r"(?i)full workflow or (a )?cut")
                self.assertNotIn(self.CHOICE_B, text)


class Closure(unittest.TestCase):
    def test_no_shipped_body_names_an_unshipped_skill(self):
        found = []
        for rel in prose():
            text = (REPO / rel).read_text(encoding="utf-8")
            for name in UNSHIPPED:
                if re.search(r"(?<![\w./-])[/`]" + re.escape(name) + r"(?![\w-])", text) \
                        and (rel, name) not in ALLOWED:
                    found.append(f"{rel}: {name}")
        self.assertEqual(found, [])

    def test_every_relative_link_resolves(self):
        broken = []
        for rel in prose():
            text = FENCE.sub("", (REPO / rel).read_text(encoding="utf-8"))
            for target in LINK.findall(text):
                path = target.split("#", 1)[0]
                if not path or re.match(r"^[a-z][a-z0-9+.-]*:", path) or path.startswith(("~", "/")):
                    continue
                if not ((REPO / rel).parent / path).exists():
                    broken.append(f"{rel} -> {target}")
        self.assertEqual(sorted(set(broken)), [])

    def test_no_shipped_file_names_a_private_factory_folder(self):
        found = [f"{rel}:{n}" for rel in tracked() if rel.startswith(("skills/", "tools/", "lib/", "bin/"))
                 for n, line in enumerate((REPO / rel).read_text(encoding="utf-8", errors="replace").splitlines(), 1)
                 if UNSHIPPED_PATHS.search(line)]
        self.assertEqual(found, [])


def denied(rel, line):
    line = PROJECT_URL.sub("", line)
    found = {hashlib.sha256(t.encode()).hexdigest()[:16] for t in TOKEN.findall(line.lower())} & DENIED
    if found and found <= CREDIT_TOKENS and rel in CREDIT_FILES and CREDIT_LINE.search(line):
        return set()
    return found


class Denylist(unittest.TestCase):
    def test_nothing_personal_ships(self):
        found = [f"{rel}:{n}" for rel in tracked()
                 for n, line in enumerate((REPO / rel).read_text(encoding="utf-8", errors="replace").splitlines(), 1)
                 if denied(rel, line)]
        self.assertEqual(found, [])

    def test_the_check_sees_a_planted_path_and_a_handle_off_a_credit_line(self):
        plant = lambda text: codecs.decode(text, "rot13")
        self.assertTrue(denied("skills/tdd/SKILL.md", plant("frr /Hfref/ebz.vyhm/abgrf")))
        self.assertTrue(denied("skills/team-lead/SKILL.md", plant("nfx ebzvyhm13 svefg")))
        self.assertFalse(denied("LICENSE", plant("Pbclevtug (p) 2026 Ebz Vyhm")))
        self.assertFalse(denied("SECURITY.md", plant("uggcf://tvguho.pbz/ebzvyhm13/zvsny/frphevgl")))
        self.assertFalse(denied("site/index.html", plant("uggcf://ebzvyhm13.tvguho.vb/zvsny/")))
        self.assertTrue(denied("site/index.html", plant("uggcf://tvguho.pbz/ebzvyhm13/zvsny ol ebzvyhm13")))
        for leak in ("/Hfref/ebzvyhm13.tvguho.vb/zvsny/abgrf", "uggcf://tvguho.pbz/ebzvyhm13/zvsny-cevingr",
                     "uggcf://ebzvyhm13.tvguho.vb/zvsny-cevingr/", "uggcf://abgtvguho.pbz/ebzvyhm13/zvsny",
                     "ebzvyhm13.tvguho.vb/zvsny", "uggcf://tvguho.pbz/ebzvyhm13/zvsny.tvg.onx"):
            self.assertTrue(denied("site/index.html", plant(leak)), plant(leak))


# Mifal's core is free and open source: nothing it ships may name, or so depend on, a paid or proprietary
# generation platform. Kept as sha256 prefixes of single lowercase tokens so this file names none of them.
# To add one, hash its lowercase token the same way; leave out ordinary English words.
PAID_SERVICES = {
    "50b2676afbe30c83", "66f4068e63b8c53e", "d931372ba7f836a0", "66c6f57f73358bfa", "1472950b8ae0b5cd",
    "5ab4f0fdb3e6cd4f", "8a105898989c6e17", "af759d1d0ef00484", "194cbf5c4433b278",
}


def names_a_paid_service(line):
    return {hashlib.sha256(t.encode()).hexdigest()[:16] for t in TOKEN.findall(line.lower())} & PAID_SERVICES


class FreeCore(unittest.TestCase):
    def test_nothing_shipped_names_a_paid_generation_service(self):
        found = [f"{rel}:{n}" for rel in tracked()
                 for n, line in enumerate((REPO / rel).read_text(encoding="utf-8", errors="replace").splitlines(), 1)
                 if names_a_paid_service(line)]
        self.assertEqual(found, [])

    def test_the_check_sees_a_planted_service_and_not_an_ordinary_word(self):
        plant = lambda text: codecs.decode(text, "rot13")
        for name in ("uvttfsvryq", "zvqwbhearl", "xvr", "qnyyr", "qnyy-r"):
            self.assertTrue(names_a_paid_service(f"use {plant(name)} for the hero"), plant(name))
        self.assertFalse(names_a_paid_service("a runway of light, a kiosk, and a cling film"))


class Provenance(unittest.TestCase):
    def setUp(self):
        self.components = json.loads((REPO / "third_party/provenance.json").read_text())["components"]

    def test_every_vendored_file_has_a_component(self):
        uncovered = [p for p in tracked() if p.startswith(("skills/", "tools/"))
                     and not any(fnmatch.fnmatch(p, g) for c in self.components for g in c["paths"])]
        self.assertEqual(uncovered, [])

    def test_every_component_names_repo_revision_and_licence_text(self):
        for c in self.components:
            with self.subTest(component=c.get("name")):
                self.assertTrue(c.get("repo") and c.get("revision") and c.get("licence"))
                self.assertTrue(c["paths"])
                self.assertTrue((REPO / c["licence_file"]).read_text().strip())

    def test_every_vendored_skill_names_its_upstream_commit_and_tree(self):
        recorded = {name: s for c in self.components for name, s in c.get("skills", {}).items()}
        own = {"engineering-workflow", "team-lead"}
        self.assertEqual(set(recorded), SHIPPED - own)
        for name, s in recorded.items():
            with self.subTest(skill=name):
                self.assertRegex(s["commit"], r"^[0-9a-f]{40}$")
                self.assertRegex(s["tree"], r"^[0-9a-f]{40}$")

    def test_every_changed_apache_file_says_so(self):
        for c in self.components:
            if c["licence"] != "Apache-2.0":
                continue
            changed = [f"skills/{name}/{f}" for name, s in c.get("skills", {}).items()
                       for f in s.get("modified", {}).get("changed", [])]
            changed += [p for p in c["paths"] if p.endswith(".md") and "/*" not in p and "SKILL.md" not in p]
            for rel in changed:
                with self.subTest(file=rel):
                    self.assertIn("Modified by Mifal", (REPO / rel).read_text())


if __name__ == "__main__":
    unittest.main()
