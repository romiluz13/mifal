import os
import signal
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import PYTHON, REPO


class RehearsalFixture:
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="mifal rehearsal test-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(PYTHON)
        self.env = {
            "HOME": str(self.root / "absent-home"),
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "TMPDIR": str(self.runtime),
            "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        }
        self.repo = self.root / "candidate"
        self.git(REPO, "clone", "-q", "--no-hardlinks", REPO, self.repo)
        (self.repo / "skills/grilling/REHEARSAL-CANDIDATE.md").write_text("candidate-only payload\n")
        self.git(self.repo, "add", "skills/grilling/REHEARSAL-CANDIDATE.md")
        self.git(self.repo, "commit", "-q", "-m", "candidate at the unchanged VERSION")
        self.candidate = self.git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def git(self, repo, *args, check=True):
        return subprocess.run(
            ["/usr/bin/git", "-C", str(repo), "-c", "user.name=rehearsal",
             "-c", "user.email=rehearsal@example.com", *map(str, args)],
            env=self.env, capture_output=True, text=True, check=check)

    def rehearse(self, tag, *prefix):
        self.assertFalse(Path(self.env["HOME"]).exists())
        process = subprocess.Popen(
            [*prefix, "/bin/bash", str(REPO / "maint/rehearse-upgrade.sh"), str(self.repo), tag],
            cwd=self.root, env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=900)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            self.fail(f"rehearsal exceeded 900 seconds\n{stdout}\n{stderr}")
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)

    def containment_profile(self):
        sandbox = shutil.which("sandbox-exec", path="/usr/bin:/bin")
        if sandbox is None:
            self.skipTest("sandbox-exec is unavailable; macOS containment was not tested")
        profile = (f'(version 1) (allow default) (deny network*) '
                   f'(deny file-write* (require-all (require-not (subpath "{self.runtime}")) '
                   f'(require-not (literal "/dev/null"))))')
        control = self.root / "escaped-write"
        blocked = subprocess.run(
            [sandbox, "-p", profile, "/bin/bash", "-c", 'echo escaped > "$1"', "--", str(control)],
            env=self.env, capture_output=True, text=True)
        if blocked.returncode == 71 and "sandbox_apply: Operation not permitted" in blocked.stderr:
            self.skipTest("sandbox-exec cannot apply a profile inside the outer sandbox")
        self.assertEqual(blocked.returncode, 1, blocked.stdout + blocked.stderr)
        self.assertIn(f"{control}: Operation not permitted", blocked.stderr)
        self.assertFalse(control.exists())
        print("PASS containment control:", blocked.stderr.strip())
        return sandbox, profile


class RehearseUpgrade(RehearsalFixture, unittest.TestCase):
    def test_an_unavailable_promised_tag_is_a_gap_and_fails(self):
        self.git(self.repo, "tag", "-d", "v0.1.0", check=False)
        result = self.rehearse("v0.1.0")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("GAP v0.1.0: no local release tag", result.stderr)
        self.assertNotIn("REHEARSAL OK:", result.stdout)

    def test_a_dirty_worktree_is_named_and_its_edits_are_excluded(self):
        self.git(self.repo, "tag", "-d", "v0.1.0", check=False)
        (self.repo / "NOTICE").write_text("uncommitted work\n")
        result = self.rehearse("v0.1.0")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("NOTE candidate uses committed HEAD; dirty worktree edits are excluded", result.stdout)
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD").stdout.strip(), self.candidate)
        self.assertEqual((self.repo / "NOTICE").read_text(), "uncommitted work\n")

    def test_containment_denies_the_specific_outside_write_without_tags(self):
        self.containment_profile()


@unittest.skipUnless(os.environ.get("MIFAL_RELEASE_REHEARSAL") == "1",
                     "historical upgrade rehearsals require MIFAL_RELEASE_REHEARSAL=1")
class ReleaseRehearsal(RehearsalFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        for tag in ("v0.1.2", "v0.2.1", "v0.2.3", "v0.3.0"):
            if self.git(self.repo, "rev-parse", "-q", "--verify", tag, check=False).returncode:
                self.skipTest(f"local historical tag {tag} is unavailable")

    def test_branch_following_upgrade_and_historical_rollback_keep_the_user_link(self):
        result = self.rehearse("v0.1.2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"PASS candidate: {self.candidate}", result.stdout)
        self.assertIn("PASS branch-following selection: v0.1.2 follows origin/main", result.stdout)
        self.assertIn("REHEARSAL OK: v0.1.2", result.stdout)
        self.assertNotIn("GAP rollback", result.stdout)

    def test_a_tag_following_path_reaches_the_candidate_tree(self):
        result = self.rehearse("v0.2.1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"PASS candidate: {self.candidate}", result.stdout)
        self.assertIn("REHEARSAL OK: v0.2.1", result.stdout)
        for tag in ("v0.1.0", "v0.1.1"):
            gap = f"GAP {tag}: no local release tag"
            if self.git(self.repo, "rev-parse", "-q", "--verify", tag, check=False).returncode:
                self.assertIn(gap, result.stdout)
            else:
                self.assertNotIn(gap, result.stdout)
        self.assertNotIn("GAP full rehearsal", result.stdout)

    def test_recent_tag_reaches_the_candidate_without_a_version_bump(self):
        result = self.rehearse("v0.3.0")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"PASS candidate: {self.candidate}", result.stdout)

    def test_an_unfixed_installer_fails_both_link_preservation_verdicts(self):
        install = self.repo / "lib/mifal/install.py"
        install.write_text(self.git(self.repo, "show", "v0.3.1:lib/mifal/install.py").stdout)
        self.git(self.repo, "add", "lib/mifal/install.py")
        self.git(self.repo, "commit", "-q", "--allow-empty", "-m", "restore the unfixed installer")
        result = self.rehearse("v0.2.1")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"(?m)^FAIL \(e\).*restored Claude link")
        self.assertRegex(result.stdout, r"(?m)^FAIL \(f\).*restored Claude link")
        self.assertNotIn("REHEARSAL OK:", result.stdout)

    def test_a_broken_candidate_update_fails_the_rehearsal(self):
        update = self.repo / "lib/mifal/update.py"
        text = update.read_text()
        signature = "def update(h, data, args, out) -> int:\n"
        self.assertEqual(text.count(signature), 1)
        update.write_text(text.replace(signature, signature + '    raise RuntimeError("broken upgrade control")\n'))
        self.git(self.repo, "add", "lib/mifal/update.py")
        self.git(self.repo, "commit", "-q", "-m", "break the candidate upgrade step")
        result = self.rehearse("v0.2.3")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("broken upgrade control", result.stdout)
        self.assertNotIn("REHEARSAL OK:", result.stdout)

    def test_an_upgrade_that_omits_a_payload_file_fails(self):
        install = self.repo / "lib/mifal/install.py"
        text = install.read_text()
        self.assertEqual(text.count('"NOTICE", '), 1)
        install.write_text(text.replace('"NOTICE", ', ""))
        self.git(self.repo, "add", "lib/mifal/install.py")
        self.git(self.repo, "commit", "-q", "-m", "omit NOTICE from the candidate payload")
        result = self.rehearse("v0.2.3")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("NOTICE: not installed or not byte-equal", result.stdout)
        self.assertIn("after the update the install is not the candidate, file for file", result.stderr)
        self.assertNotIn("REHEARSAL OK:", result.stdout)

    def test_payload_repair_needs_no_real_homes_and_writes_only_in_its_disposable_area(self):
        forbidden = self.root / "forbidden-home"
        forbidden.mkdir()
        (forbidden / "AGENTS.md").write_text("untouched user rule\n")
        for variable in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "PI_CODING_AGENT_DIR",
                         "FACTORY_HOME_OVERRIDE", "OPENCODE_CONFIG_DIR", "XDG_CONFIG_HOME"):
            self.env[variable] = str(forbidden)
        sandbox, profile = self.containment_profile()
        profile += f' (deny file-read* (subpath "{forbidden}"))'
        result = self.rehearse("v0.2.3", sandbox, "-p", profile)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS isolation: disposable HOME", result.stdout)
        self.assertIn(f"PASS candidate: {self.candidate}", result.stdout)
        self.assertFalse(Path(self.env["HOME"]).exists())
        self.assertEqual((forbidden / "AGENTS.md").read_text(), "untouched user rule\n")


if __name__ == "__main__":
    unittest.main()
