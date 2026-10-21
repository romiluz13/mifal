# Maintaining Mifal

Mifal stands on things that move: other people's skills, Herdr, and five agents' rules-file conventions. This page says how each kind of change gets in, how a change of Mifal's goes back upstream, and how a release reaches users. Every step ends in `tests/run.sh -q` passing under both Pythons.

## Vendored skills

`third_party/provenance.json` records, for every vendored skill, its upstream repo and folder, the commit it was taken from, that folder's tree, and the files Mifal changed. `maint/upstream.py` works from that record.

```sh
python3 maint/upstream.py status          # what changed upstream since each recorded commit (exit 1 when anything did)
python3 maint/upstream.py pull tdd grill-me
python3 maint/upstream.py diff tdd        # Mifal's own changes to tdd, against the upstream it came from
```

`pull` merges each file three ways: the recorded upstream commit is the base, `skills/NAME` is Mifal's side, the upstream head is theirs. A file only upstream changed takes upstream's version; a file only Mifal changed stays; a file both changed is merged by `git merge-file`, and overlapping edits are left as conflict markers, listed, with exit 1. Upstream additions and deletions apply where Mifal did not touch the file; a file deleted on one side and changed on the other is kept as it is in Mifal and listed. `pull` then rewrites the skill's commit, tree and changed-file list. It never commits. It copies regular files only, with upstream's executable bit: a symlink in `skills/NAME` or among upstream's files stops it before it writes anything, and that skill is taken by hand.

After a pull:

1. Resolve any conflict markers. Keep Mifal's scrubs: `tests/test_content.py` fails on a personal string coming back.
2. `/bin/bash maint/rebuild-inventory.sh`, so the team lead's skill inventory matches the new skills. Run it only after a change under `skills/`; on its own it only moves the inventory's timestamp.
3. `/bin/bash tests/run.sh -q`, then the full `/bin/bash tests/run.sh` before a release.
4. Review the diff as any change, commit, release.

`status` also lists skills that sit next to a vendored one upstream but are not shipped, so a new upstream skill is seen. Taking one in is a decision, not a sync: copy the folder, add its record to `provenance.json` (`"repo"`, `"upstream"`, `"commit"`, `"tree"`, `"modified"`), and add it to `SHIPPED` in `tests/test_content.py`.

Impeccable and LottieFiles were adapted into `skills/frontend-design/references/interface/` by hand, so `status` reports their new upstream commits and they are read and adapted by hand. Update the component's `revision` when you have.

The weekly `upstream` workflow runs `status` on GitHub and keeps one issue open while anything is behind.

## Offering a change upstream

`python3 maint/upstream.py diff NAME` prints Mifal's changes as a patch against the upstream folder's own paths. In a clone of the upstream at the recorded commit, `git apply` takes it; keep the part that is general, drop what is Mifal-specific, and open the PR there. Once upstream merges it, the next `pull` finds nothing to merge in that file and records it as unmodified.

## Herdr

The team lead's adapter (`tools/herdr_adapter/`) speaks Herdr's socket protocol 22 and keeps the exact schema it was built for in `tools/herdr_adapter/api-schema.json`. `mifal doctor` compares it with `herdr api schema --json` from the user's Herdr: identical passes; a changed schema within the protocol warns; another protocol warns too, because only the adapter refuses it and the team lead's raw `herdr` commands keep working. The adapter is experimental: the team lead works without it.

When Herdr ships a new protocol:

1. `herdr api schema --json --output tools/herdr_adapter/api-schema.json` with the new Herdr, and read the diff.
2. Update the adapter for what changed, including the protocol check in `adapter.py`.
3. Run the adapter suite (`tests/run.sh` runs it) and one live lead-to-worker round trip.
4. Raise `MINIMUM` in `lib/mifal/herdr.py` if the new adapter needs the new Herdr, then release.

The vendored `herdr` skill updates through `maint/upstream.py` like any other.

## The five agents

`lib/mifal/harness.py` holds what Mifal knows about each agent: where its home folder is and which variable moves it, which rules file it reads first, and whether it reads `~/.agents/skills` itself. `tests/test_wiring.py` holds each fact as a test. When an agent changes its conventions:

1. Read the agent's docs or source at the new version, and keep the link in the commit message.
2. Change the test first, then `harness.py`.
3. The doctor re-reads precedence on every run, so users with a now-wrong wiring see a FAIL with the fix after they update Mifal.

| Agent | Rules file Mifal writes | Read first instead, when present | Skills |
|---|---|---|---|
| Claude Code | `$CLAUDE_CONFIG_DIR/CLAUDE.md` (a block that imports the Guide) | | links in `$CLAUDE_CONFIG_DIR/skills/` |
| Codex | `$CODEX_HOME/AGENTS.md` | `AGENTS.override.md` | native |
| Droid | `~/.factory/AGENTS.md` | | native |
| Pi | `$PI_CODING_AGENT_DIR/AGENTS.md` | `AGENTS.override.md`, then `AGENTS.md`, `AGENTS.MD`, `CLAUDE.md`, `CLAUDE.MD` | native |
| OpenCode | `AGENTS.md` in its config folder | `~/.claude/CLAUDE.md` is its fallback when its own file is absent, unless `OPENCODE_DISABLE_CLAUDE_CODE` or `..._PROMPT` is `true` or `1` | native |

## The routine

One maintainer, several agents. Production is `main`; everything else is short-lived.

1. **Dogfood first.** Try a change in your own setup. A change that proves itself there becomes a pull request here; nothing flows back automatically.
2. **One branch, one worktree, one writer per task.** `git worktree add ../.worktrees/mifal/<task> -b agent/<who>-<topic> main`. Check `git worktree list` before starting, so two agents never share a branch or a folder. Never work in the folder you installed from.
3. **Pull request, then merge.** `main` takes only pull requests whose `mifal` check passed; merged branches delete themselves.
4. **Release on purpose.** Follow Releasing below. Only a pushed `vX.Y.Z` tag reaches users, and a tag cannot be moved or deleted, so a bad release is fixed by the next one.
5. **Weekly cleanup.** `git fetch --prune`, `git worktree prune`, and `git branch --merged main`; delete a branch only after checking that it holds no commit `main` lacks (`git log main..<branch>`). Remove the worktrees of merged branches.
6. **Never:** force-push, push to `main`, delete a tag, or edit a shipped file inside an installed copy.

What publishes what: merging a pull request that changes `site/` publishes the website within about a minute. Only a pushed `vX.Y.Z` tag gives users a new version. Merging code to `main` alone changes neither for users.

Words to give a coding agent:

- Start: "In the Mifal clone, create a worktree and branch `agent/<you>-<topic>` from `origin/main`. Do `<task>`. Run `tests/run.sh -q`. Do not push."
- Publish a website change: "Open a pull request for this branch. Wait for the `mifal` check. Show me the diff and screenshots. Wait for my yes, then squash-merge and confirm the Pages deploy passed."
- Release to users: "Raise `VERSION` to X in a pull request. Wait for the `release` workflow to pass. After my yes, merge it, tag that exact merge commit `vX`, push the tag, and confirm the tag's run passed."

## Releasing

`main` is protected: every change goes in by pull request, and the `mifal` check must pass. Release tags `v*` cannot be moved or deleted. `mifal update` follows the newest `vX.Y.Z` tag, so merging to `main` does not reach users; tagging does.

1. `VERSION` holds the release; raise it, in a pull request, for any change users get.
2. In that pull request, run the full suite, `/bin/bash tests/run.sh`, under both Pythons on macOS, and `/bin/bash maint/rehearse-upgrade.sh <repo> <previous tag>`; the `release` workflow runs both when `VERSION` changes.
3. Merge it, then tag that merge commit `vX.Y.Z` (the `release` workflow checks that the tag equals `VERSION` and sits on `main`) and push the tag. Tags are permanent, so a release found broken is fixed by the next version.
4. Users run `mifal update`: it fetches their clone, previews the incoming commits and every write, asks, and installs exactly the revision it showed.

Installs from 0.1.2 or earlier follow the branch, not tags: an update at any later time runs the old code and lands on the tip of `main`, and from then on the install runs the tag-following code. Keep `main` releasable, and keep it at the release commit until you have tagged it, so that landing is a release.

A tag counts only if it is `vX.Y.Z`, sits on the branch the clone tracks, and its `VERSION` file is the tag. A mistyped or off-branch tag is ignored by `mifal update`. Tags are still permanent. A fork that keeps its own commits without tagging follows them with `mifal update --branch`.
