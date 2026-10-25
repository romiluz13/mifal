import json
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

    def drop_licences(self):
        """The state a 0.2.3 update leaves: the engine without NOTICE and third_party/, and a Manifest that omits them."""
        engine = (self.home / ".agents/mifal").resolve()
        mine = lambda path: path == str(engine / "NOTICE") or path.startswith(str(engine / "third_party"))
        data = self.manifest()
        data["entries"] = [e for e in data["entries"] if not mine(e["path"])]
        (self.home / ".agents/mifal/install-manifest.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        (engine / "NOTICE").unlink()
        shutil.rmtree(engine / "third_party")
        self.installed = snapshot(self.home)

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
        self.cut("0.2.5")
        self.publish("after the release", **{"skills/grilling/NOTE.md": "unreleased\n"})
        self.git(self.clone, "pull", "-q", "--ff-only")
        self.install()
        installed = snapshot(self.home)
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("already includes release v0.2.5", result.stdout)
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


class OpenCode(Update):
    """An install that served no agent when it was made: update wires an agent found since, as an install does."""

    def test_an_update_that_newly_wires_opencode_stops_on_the_claude_fallback_until_overwrite_edits(self):
        self.harness_fakes("opencode")
        moved = self.home / "elsewhere"
        fallback = moved / ".claude/CLAUDE.md"
        fallback.parent.mkdir(parents=True)
        fallback.write_text("my claude rules\n")
        self.publish(**{"skills/grilling/NOTE.md": "note\n"})
        before = snapshot(self.home)
        result = self.update("--yes", OPENCODE_TEST_HOME=str(moved))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("~/elsewhere/.claude/CLAUDE.md: OpenCode reads it now, and stops once Mifal writes "
                      "~/.config/opencode/AGENTS.md", result.stdout)
        self.assertIn("Nothing was changed.", result.stdout)
        self.assertIn("mifal update --overwrite-edits", result.stdout)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(self.head(), self.old)
        result = self.update("--overwrite-edits", "--yes", OPENCODE_TEST_HOME=str(moved))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("block ~/.config/opencode/AGENTS.md", result.stdout)
        self.assertEqual(self.manifest()["harnesses"]["opencode"]["status"], "wired")
        self.assertEqual(fallback.read_text(), "my claude rules\n")


class Skipped(Update):
    """An agent the Manifest records as skipped is planned again, at its recorded home, as the install would plan it."""

    def record_skipped(self, name, root, rules):
        """Mark name as skipped in the Manifest, as Mifal 0.2.x recorded an OpenCode that read the Claude fallback."""
        data = self.manifest()
        data["harnesses"][name] = {"root": os.path.realpath(root), "rules": os.path.realpath(root) + "/" + rules,
                                   "status": "skipped"}
        (self.home / ".agents/mifal/install-manifest.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    def skipped_opencode(self):
        """A Claude install whose Manifest records OpenCode as skipped, with a release waiting; the Claude rules file."""
        self.harness_fakes("claude", "opencode")
        fallback = self.home / ".claude/CLAUDE.md"
        fallback.parent.mkdir(parents=True)
        fallback.write_text("my claude rules\n")
        self.install("--harness", "claude")
        self.record_skipped("opencode", self.home / ".config/opencode", "AGENTS.md")
        self.publish(**{"skills/grilling/NOTE.md": "note\n"})
        return fallback

    def test_an_update_plans_a_skipped_opencode_and_stops_on_the_claude_fallback_until_overwrite_edits(self):
        fallback = self.skipped_opencode()
        before = snapshot(self.home)
        result = self.update("--yes")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("~/.claude/CLAUDE.md: OpenCode reads it now, and stops once Mifal writes "
                      "~/.config/opencode/AGENTS.md", result.stdout)
        self.assertNotIn("found opencode", result.stdout)
        self.assertIn("Nothing was changed.", result.stdout)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(self.head(), self.old)
        result = self.update("--overwrite-edits", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("block ~/.config/opencode/AGENTS.md", result.stdout)
        self.assertEqual(self.manifest()["harnesses"]["opencode"]["status"], "wired")
        self.assertEqual((self.home / ".config/opencode/AGENTS.md").read_text().count("<!-- mifal:begin "), 1)
        self.assertTrue(fallback.read_text().startswith("my claude rules\n"))

    def test_the_fallback_stop_says_what_overwrite_edits_accepts_and_neither_moves_nor_saves_the_file(self):
        self.skipped_opencode()
        result = self.update("--yes")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("For ~/.claude/CLAUDE.md: Mifal leaves it as it is. Run mifal update --overwrite-edits to "
                      "accept that OpenCode then reads ~/.config/opencode/AGENTS.md instead.", result.stdout)
        for wrong in ("Restore those paths", "save a copy", "saved", "move"):
            self.assertNotIn(wrong, result.stdout.lower() if wrong == "move" else result.stdout)

    def test_an_agent_whose_skip_still_holds_stays_skipped_with_its_note(self):
        self.harness_fakes("claude", "pi")
        (self.home / ".pi/agent").mkdir(parents=True)
        (self.home / ".pi/agent/CLAUDE.md").write_text("my pi rules\n")
        self.install("--harness", "claude", "--harness", "pi")
        self.assertEqual(self.manifest()["harnesses"]["pi"]["status"], "skipped")
        self.publish(**{"skills/grilling/NOTE.md": "note\n"})
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("skip pi: it reads ~/.pi/agent/CLAUDE.md now", result.stdout)
        self.assertNotIn("found pi", result.stdout)
        self.assertEqual(self.manifest()["harnesses"]["pi"]["status"], "skipped")
        self.assertFalse((self.home / ".pi/agent/AGENTS.md").exists())

    def test_a_skipped_agent_is_planned_at_its_recorded_home_not_the_default_one(self):
        self.harness_fakes("claude", "codex")
        alt = self.home / "alt-codex"
        alt.mkdir()
        (alt / "AGENTS.override.md").write_text("my override\n")
        (self.home / ".codex").mkdir()
        self.install("--harness", "claude", "--harness", "codex", CODEX_HOME=str(alt))
        self.assertEqual(self.manifest()["harnesses"]["codex"]["status"], "skipped")
        self.publish(**{"skills/grilling/NOTE.md": "note\n"})
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("skip codex: it reads ~/alt-codex/AGENTS.override.md", result.stdout)
        self.assertFalse((self.home / ".codex/AGENTS.md").exists())
        self.assertFalse((alt / "AGENTS.md").exists())


class Reserved(Update):
    """A release reserves a name that a skill of the person's already uses."""

    def reserve(self):
        self.publish("add a commit skill", **{"skills/commit/SKILL.md": "mifal commit\n"})

    def theirs(self):
        path = self.home / ".agents/skills/commit/SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text("my commit skill\n")
        return path

    def test_the_update_stops_and_changes_nothing_when_a_skill_of_yours_has_the_new_name(self):
        theirs = self.theirs()
        self.reserve()
        before = snapshot(self.home)
        result = self.update("--yes")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("~/.agents/skills/commit: exists and was not installed by Mifal, but this release installs "
                      "its own at that path", result.stdout)
        self.assertNotIn("~/.agents/skills/commit/SKILL.md", result.stdout)
        self.assertIn("Nothing was changed.", result.stdout)
        self.assertIn("mifal update --overwrite-edits", result.stdout)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(self.head(), self.old)
        self.assertEqual(theirs.read_text(), "my commit skill\n")

    def test_overwrite_edits_backs_the_skill_up_then_installs_the_release_copy_and_doctor_notes_it(self):
        theirs = self.theirs()
        self.reserve()
        result = self.update("--overwrite-edits", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"backup ~/.agents/skills/commit -> "
                                        r"~/.agents/mifal/backup/\d{8}T\d{6}Z/.agents/skills/commit")
        self.assertEqual(theirs.read_text(), "mifal commit\n")
        saved = list((self.home / ".agents/mifal/backup").glob("*/.agents/skills/commit/SKILL.md"))
        self.assertEqual([p.read_text() for p in saved], ["my commit skill\n"])
        doctor = self.mifal("doctor", check=False)
        self.assertRegex(doctor.stdout, r"(?m)^note 1 skill folder\(s\) or link\(s\) of yours are saved in "
                                        r"~/.agents/mifal/backup, where Mifal moved them to take their names\. ")
        self.assertIn("mifal uninstall puts each back", doctor.stdout)
        self.assertNotRegex(doctor.stdout, r"(?m)^(WARN|FAIL) .*backup")
        self.mifal("uninstall")
        self.assertEqual(theirs.read_text(), "my commit skill\n")

    def test_a_claude_link_of_yours_with_the_new_name_stops_the_update_and_is_restored_by_uninstall(self):
        self.harness_fakes("claude")
        self.install("--harness", "claude")
        mine = self.home / "mine/commit"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("my commit skill\n")
        link = self.home / ".claude/skills/commit"
        link.symlink_to(mine)
        self.reserve()
        before = snapshot(self.home)
        result = self.update("--yes")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("~/.claude/skills/commit: exists and was not installed by Mifal", result.stdout)
        self.assertEqual(snapshot(self.home), before)
        result = self.update("--overwrite-edits", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(os.readlink(link), os.path.realpath(self.home / ".agents/skills/commit"))
        self.assertEqual((mine / "SKILL.md").read_text(), "my commit skill\n")
        self.mifal("uninstall")
        self.assertEqual(os.readlink(link), str(mine))

    def test_a_name_the_install_already_owns_does_not_stop_the_update(self):
        self.publish(**{"skills/grilling/NOTE.md": "note\n"})
        extra = self.home / ".agents/skills/grilling/mine.md"
        extra.write_text("my notes\n")
        result = self.update("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(extra.read_text(), "my notes\n")


if __name__ == "__main__":
    unittest.main()
