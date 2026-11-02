# 00: Version the agency tree

**What to build:** The whole `~/.agents` tree becomes a git repository, so every stewardship
change the lead ever makes (skills, configs, inventories, records) is reviewable history
instead of silent edits. Caches and volatile artifacts are ignored; real configuration is
tracked. Includes an alignment audit: the repo layout must respect the existing agency
configuration (skill scopes, invocation policy, the skill lock file, the skills catalog,
maintenance scripts) — nothing may break the update/sync workflows the human already runs.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] `git init` on the whole `~/.agents` tree; initial baseline commit lands clean
- [x] `.gitignore` excludes caches and volatile artifacts (Python caches, `.DS_Store`,
      scratch/skill-workspaces state) while tracking real config and skill content
- [x] The lock file, scopes, invocation policy, catalog, and maintenance scripts survive
      a sync/update run unbroken (run the update scripts; nothing errors or diffs oddly)
- [x] A stewardship edit made afterwards shows up as a reviewable commit (demo: one
      documented change, one commit)
- [x] README of the team-lead skill points contributors/implementers at the repo convention
