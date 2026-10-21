import os
import shutil
import subprocess
import unittest

from support import Sandbox, changed, snapshot
from test_lifecycle import normalized, planned_paths


class Update(Sandbox):
    """A clone with a local bare repo as its origin, installed from."""

    def setUp(self):
        super().setUp()
        self.origin = self.root / "origin.git"
        self.git(self.clone, "init", "-q", "-b", "main")
        self.git(self.clone, "add", "-A")
        self.git(self.clone, "commit", "-q", "-m", "release 0.1.0")
        self.git(self.root, "clone", "-q", "--bare", self.clone, self.origin)
        self.git(self.clone, "remote", "add", "origin", self.origin)
        self.git(self.clone, "fetch", "-q", "origin")
        self.git(self.clone, "branch", "-q", "--set-upstream-to=origin/main")
        self.work = self.root / "work"
        self.git(self.root, "clone", "-q", self.origin, self.work)
        self.install()
        self.installed = snapshot(self.home)
        self.old = self.head()

    def git(self, cwd, *args):
        env = dict(self.env(), GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        return subprocess.run(["git", "-C", str(cwd), *map(str, args)], env=env, capture_output=True, text=True,
                              check=True, stdin=subprocess.DEVNULL).stdout.strip()

    def head(self, repo=None):
        return self.git(repo or self.clone, "rev-parse", "HEAD")

    def publish(self, message="add a note", **files):
        """Commit files (path: text, or None to delete) in the upstream work tree and push them to origin."""
        for rel, text in files.items():
            path = self.work / rel
            if text is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-q", "-m", message)
        self.git(self.work, "push", "-q", "origin", "main")
        return self.head(self.work)

    def update(self, *args, **kw):
        return self.mifal("update", *args, check=False, **kw)

    def update_in_terminal(self, answer, *args):
        return self.run_in_terminal("/bin/bash", self.home / ".local/bin/mifal", "update", *args, answer=answer)


class Preview(Update):
    def test_the_preview_shows_the_commit_and_no_changes_nothing_and_yes_installs_it(self):
        new = self.publish("add a grilling note", **{"skills/grilling/NOTE.md": "note\n"})
        result = self.update_in_terminal("n\n")
        self.assertIn("add a grilling note", result.stdout)
        self.assertIn("create ~/.agents/skills/grilling/NOTE.md", result.stdout)
        self.assertEqual(snapshot(self.home), self.installed)
        self.assertEqual(self.head(), self.old)
        result = self.update_in_terminal("y\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.home / ".agents/skills/grilling/NOTE.md").read_text(), "note\n")
        self.assertEqual(self.manifest()["source"]["revision"], new)
        self.assertEqual(self.head(), new)

    def test_non_interactive_without_yes_changes_nothing(self):
        self.publish(**{"skills/grilling/NOTE.md": "note\n"})
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--yes", result.stdout)
        self.assertEqual(snapshot(self.home), self.installed)
        self.assertEqual(self.head(), self.old)

    def test_up_to_date_says_so(self):
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("up to date", result.stdout)

    def test_the_preview_lists_exactly_the_writes_when_the_write_set_changes(self):
        new = self.publish("add a skill, drop a file", **{"skills/grilling/SKILL.md": None,
                                                           "skills/grilling/STEPS.md": "steps\n"})
        preview = self.update()
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.manifest()["source"]["revision"], new)
        self.assertEqual(normalized(planned_paths(preview.stdout)),
                         normalized(changed(self.installed, snapshot(self.home))))

    def test_only_the_approved_revision_lands_when_origin_advances_during_the_prompt(self):
        approved = self.publish("first", **{"skills/grilling/NOTE.md": "first\n"})
        advance = self.root / "advance.sh"
        advance.write_text(f'#!/bin/bash\ncd "{self.work}" && echo second > skills/grilling/NOTE.md && '
                           'git add -A && git commit -q -m second && git push -q origin main\n')
        advance.chmod(0o755)
        self.fake("git", f'if [ "$1 $2 $3" = "-C {self.clone} log" ]; then "{advance}" >/dev/null 2>&1; fi\n'
                         'exec /usr/bin/git "$@"')
        result = self.update("--yes", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                             GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotEqual(self.head(self.work), approved)
        self.assertEqual(self.head(), approved)
        self.assertEqual(self.manifest()["source"]["revision"], approved)
        self.assertEqual((self.home / ".agents/skills/grilling/NOTE.md").read_text(), "first\n")


class Releases(Update):
    """With release tags on the remote the update follows the newest valid vX.Y.Z tag, not the branch."""

    def tag(self, name, *args):
        self.git(self.work, "tag", *args, name)
        self.git(self.work, "push", "-q", "origin", name)

    def cut(self, version, note=None, *args):
        """Publish a commit whose VERSION is version, tag it v<version>, and return its sha."""
        sha = self.publish(f"release {version}", VERSION=version + "\n",
                           **{"skills/grilling/NOTE.md": (note or version) + "\n"})
        self.tag("v" + version, *args)
        return sha

    def note(self):
        return (self.home / ".agents/skills/grilling/NOTE.md").read_text().strip()

    def test_the_newest_release_is_installed_and_commits_after_it_are_not(self):
        released = self.cut("0.2.0")
        self.publish("after the release", **{"skills/grilling/NOTE.md": "unreleased\n"})
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("release v0.2.0", result.stdout)
        self.assertEqual(self.head(), released)
        self.assertEqual(self.manifest()["source"]["revision"], released)
        self.assertEqual(self.note(), "0.2.0")

    def test_a_commit_on_the_branch_that_is_not_released_is_not_offered(self):
        self.tag("v" + (self.work / "VERSION").read_text().strip(), "-a", "-m", "the release the install is at")
        self.publish("site only", **{"skills/grilling/NOTE.md": "note\n"})
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("up to date", result.stdout)
        self.assertEqual(snapshot(self.home), self.installed)
        self.assertEqual(self.head(), self.old)

    def test_a_release_the_install_is_already_past_is_current(self):
        self.cut("0.2.0")
        self.publish("after the release", **{"skills/grilling/NOTE.md": "unreleased\n"})
        self.git(self.clone, "pull", "-q", "--ff-only")
        self.install()
        installed = snapshot(self.home)
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("already includes release v0.2.0", result.stdout)
        self.assertEqual(snapshot(self.home), installed)

    def test_a_clone_pulled_past_the_release_still_installs_it_when_the_install_is_older(self):
        released = self.cut("0.2.0")
        self.publish("after the release", **{"skills/grilling/NOTE.md": "unreleased\n"})
        self.git(self.clone, "pull", "-q", "--ff-only")
        ahead = self.head()
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.manifest()["source"]["revision"], released)
        self.assertEqual(self.note(), "0.2.0")
        self.assertEqual(self.head(), ahead)

    def test_versions_sort_numerically_and_prereleases_are_not_releases(self):
        self.cut("0.9.0")
        ten = self.cut("0.10.0", None, "-a", "-m", "release 0.10.0")
        self.publish("candidate", VERSION="0.11.0-rc1\n")
        self.tag("v0.11.0-rc1")
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("release v0.10.0", result.stdout)
        self.assertEqual(self.head(), ten)

    def test_a_tag_whose_version_file_disagrees_is_ignored(self):
        good = self.cut("0.2.0")
        self.publish("mistaken tag", **{"skills/grilling/NOTE.md": "oops\n"})
        self.tag("v2.0.0")
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("release v0.2.0", result.stdout)
        self.assertEqual(self.head(), good)

    def test_a_tag_that_is_not_on_the_branch_is_ignored(self):
        good = self.cut("0.2.0")
        self.git(self.work, "checkout", "-q", "-b", "hotfix", self.old)
        (self.work / "VERSION").write_text("3.0.0\n")
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-q", "-m", "hotfix")
        self.tag("v3.0.0")
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("release v0.2.0", result.stdout)
        self.assertEqual(self.head(), good)

    def test_a_tag_of_the_users_own_cannot_become_the_release(self):
        good = self.cut("0.2.0")
        self.git(self.clone, "tag", "v9.0.0", self.old)
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("release v0.2.0", result.stdout)
        self.assertEqual(self.head(), good)

    def test_a_local_tag_with_a_remote_tags_name_does_not_stop_the_update(self):
        good = self.cut("0.2.0")
        self.git(self.clone, "tag", "v0.2.0", self.old)
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(), good)

    def test_non_ascii_digits_are_not_a_version(self):
        good = self.cut("0.2.0")
        self.publish("odd tag", VERSION="\u0661.0.0\n")
        self.tag("v\u0661.0.0")
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(), good)

    def test_branch_follows_the_branch_even_when_releases_exist(self):
        self.cut("0.2.0")
        tip = self.publish("after the release", **{"skills/grilling/NOTE.md": "unreleased\n"})
        result = self.update("--yes", "--branch")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(), tip)
        self.assertEqual(self.note(), "unreleased")

    def test_a_diverged_clone_is_still_refused_with_a_release(self):
        self.cut("0.2.0")
        (self.clone / "LOCAL.md").write_text("local\n")
        self.git(self.clone, "add", "-A")
        self.git(self.clone, "commit", "-q", "-m", "local work")
        local = self.head()
        result = self.update("--yes")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("not a fast-forward", result.stdout)
        self.assertEqual(self.head(), local)

    def test_without_release_tags_the_recorded_branch_is_followed(self):
        new = self.publish("untagged remote", **{"skills/grilling/NOTE.md": "note\n"})
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(), new)


class Refusals(Update):
    def refused(self, reason):
        result = self.update("--yes")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertRegex(result.stdout, reason)
        self.assertEqual(snapshot(self.home), self.installed)
        return result

    def test_a_non_fast_forward_origin_is_refused(self):
        self.git(self.work, "commit", "-q", "--amend", "-m", "rewritten history")
        self.git(self.work, "push", "-q", "--force", "origin", "main")
        self.refused("not a fast-forward")
        self.assertEqual(self.head(), self.old)

    def test_a_diverged_clone_is_refused(self):
        self.publish(**{"skills/grilling/NOTE.md": "note\n"})
        (self.clone / "LOCAL.md").write_text("local\n")
        self.git(self.clone, "add", "-A")
        self.git(self.clone, "commit", "-q", "-m", "local work")
        local = self.head()
        self.refused("not a fast-forward")
        self.assertEqual(self.head(), local)

    def test_a_dirty_tracked_file_is_refused(self):
        self.publish(**{"skills/grilling/NOTE.md": "note\n"})
        (self.clone / "README.md").write_text("changed locally\n")
        self.refused("uncommitted changes")
        self.assertEqual(self.head(), self.old)

    def test_an_unfetched_candidate_is_refused(self):
        self.git(self.clone, "config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/elsewhere")
        (self.clone / ".git/refs/remotes/origin/main").write_text("1" * 40 + "\n")
        self.refused(r"git fetch --quiet origin failed .*bad object")
        self.assertEqual(self.head(), self.old)

    def test_without_a_recorded_clone_it_prints_the_two_commands(self):
        shutil.rmtree(self.clone)
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("git clone", result.stdout)
        self.assertIn("./install.sh", result.stdout)
        self.assertEqual(snapshot(self.home), self.installed)


class Recovery(Update):
    def test_a_failed_fast_forward_rolls_the_install_back_and_keeps_the_clone(self):
        self.publish(**{"skills/grilling/NOTE.md": "note\n"})
        result = self.update("--yes", MIFAL_TEST_FAIL_AT="fast-forward")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot(self.home), self.installed)
        self.assertEqual(self.head(), self.old)

    def test_a_crash_after_the_fast_forward_is_rolled_back_and_the_candidate_is_offered_again(self):
        new = self.publish(**{"skills/grilling/NOTE.md": "note\n"})
        result = self.update("--yes", MIFAL_TEST_FAIL_AT="after-fast-forward:exit")
        self.assertEqual(result.returncode, 70, result.stdout + result.stderr)
        self.assertEqual(self.head(), new)
        result = self.update()
        self.assertIn(self.old[:12], result.stdout)
        self.assertIn(new[:12], result.stdout)
        self.assertIn(f"run ./install.sh in {self.clone}", result.stdout)
        self.assertEqual(snapshot(self.home), self.installed)
        self.assertEqual(self.manifest()["source"]["revision"], self.old)
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.manifest()["source"]["revision"], new)
        self.assertTrue((self.home / ".agents/skills/grilling/NOTE.md").exists())


if __name__ == "__main__":
    unittest.main()
