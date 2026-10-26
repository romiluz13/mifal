import shutil
import unittest

from support import Sandbox

SCRIPTS = ".agents/skills/team-lead/scripts"
FIXTURES = SCRIPTS + "/fixtures"
ADAPTER = ".agents/mifal/tools/herdr_adapter"


class InstalledValidator(Sandbox):
    """The contract validator works from the installed Pool alone, with the clone gone."""

    def setUp(self):
        super().setUp()
        self.install()
        shutil.rmtree(self.clone)
        self.validator = self.home / SCRIPTS / "validate_contracts.py"

    def validate(self, *args, check=True):
        return self.run_cmd("python3", "-B", self.validator, *args, check=check)

    def test_selfcheck_passes(self):
        self.assertIn("pass", self.validate("selfcheck").stdout)

    def shipped_test(self, name):
        result = self.run_cmd("python3", "-B", "-m", "unittest", name, check=False,
                              PYTHONPATH=str(self.home / SCRIPTS))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Ran 1 test", result.stderr)

    def test_a_matt_brief_from_the_installed_template_passes(self):
        self.shipped_test("test_workflow_teaching.GrillerBriefTests.test_the_filled_template_passes_the_matt_brief_check")

    def test_a_matt_receipt_passes_and_one_without_its_record_is_refused(self):
        self.shipped_test("test_workflow_contracts.WorkflowTests.test_receipt_checks_the_matt_brief_as_well_as_the_return")

    def test_a_good_receipt_passes_and_a_broken_one_is_refused(self):
        self.validate("receipt", self.home / FIXTURES / "receipt/good/receipt-7.md")
        refused = self.validate("receipt", self.home / FIXTURES / "receipt/bad/missing-claims.md", check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertNotIn("Traceback", refused.stderr)

    def imports_installed(self, *modules):
        """Import the installed adapter modules in a fresh interpreter; import-time wiring only."""
        return self.run_cmd("python3", "-B", "-c",
                            "import sys; sys.path.insert(0, sys.argv[1]); import " + ", ".join(modules),
                            str(self.home / ADAPTER))

    def test_the_installed_adapter_imports_lead_wake_preflight_and_resume(self):
        result = self.imports_installed("lead", "wake", "preflight", "resume")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_installed_lead_resolves_the_pool_scripts(self):
        result = self.run_cmd("python3", "-B", "-c",
                              "import sys; sys.path.insert(0, sys.argv[1]); import lead; print(lead.SCRIPTS)",
                              str(self.home / ADAPTER))
        self.assertEqual(result.stdout.strip(), str(self.home / SCRIPTS))


class InstalledLicences(Sandbox):
    """The licences and provenance travel with the install: the clone can go and they stay, byte for byte."""

    LICENCES = "frontend-design/references/interface/licenses"

    def tree(self, base):
        return {str(p.relative_to(base)): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}

    def test_the_install_carries_notice_and_third_party_and_uninstall_removes_them(self):
        self.install()
        engine = self.home / ".agents/mifal"
        source = self.clone / "third_party"
        self.assertEqual(len(self.tree(source)), 15)
        self.assertEqual(self.tree(engine / "third_party"), self.tree(source))
        self.assertEqual((engine / "NOTICE").read_bytes(), (self.clone / "NOTICE").read_bytes())
        for name in ("IMPECCABLE-LICENSE", "LOTTIEFILES-LICENSE"):
            self.assertEqual((self.home / ".agents/skills" / self.LICENCES / name).read_bytes(),
                             (self.clone / "skills" / self.LICENCES / name).read_bytes())
        self.mifal("uninstall")
        self.assertFalse((engine / "NOTICE").exists())
        self.assertFalse((engine / "third_party").exists())


class CloneAdapter(Sandbox):
    """In a clone, lead.py still resolves the repository's own skills folder."""

    def test_clone_lead_resolves_the_repository_scripts(self):
        result = self.run_cmd("python3", "-B", "-c",
                              "import sys; sys.path.insert(0, sys.argv[1]); import lead; print(lead.SCRIPTS)",
                              str(self.clone / "tools/herdr_adapter"))
        self.assertEqual(result.stdout.strip(), str(self.clone / "skills/team-lead/scripts"))


if __name__ == "__main__":
    unittest.main()
