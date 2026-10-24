# Mifal Guide

Rules for sessions that load this Mifal Guide, installed by Mifal. Repository instructions add to them; the user's request and the harness's safety rules come first.

## Engineering workflow

- Matt owns engineering in every harness.
- Before acting on a research, planning, build, debug or review request, load the `engineering-workflow` skill completely and follow it: through your native skill tool when you have one (in Claude Code, the Skill tool), otherwise by reading `~/.agents/skills/engineering-workflow/SKILL.md`.
- Invoke a skill on your own when its description matches the task; a slash command is not needed. Load only the specialist you selected. A skill's external actions, such as publishing, messaging or deploying, still need their own authorization.
- For sustained coordination of engineering work across Herdr panes, read `~/.agents/skills/team-lead/references/herdr.md` before the first dispatch, and run its pane checks before every prompt.

## Skills pool

- `~/.agents/skills/` holds the skills Mifal installed. Claude Code reaches it through one link per skill; the other agents are expected to read it directly (not yet live-checked).
- Update Mifal and its skills with `mifal update`. Check an install with `mifal doctor`. A skill you edit is kept: Mifal stops before overwriting it and tells you how to keep or replace it.

## Working style

- Report the outcome first, then what changed, the checks you ran and what remains unverified.
- Keep secrets out of the transcript: refer to `.env*`, credential, token and settings files by path, and never print their contents.
- Follow a rule's purpose, not only its wording: a loophole that lets you skip a gate is a bug in the rule, not permission to skip it.
- State material assumptions. Continue on low-risk, reversible choices; ask when missing information changes scope, safety or the design.
- Plan before starting work of three or more steps, cross-file changes or material risk. When evidence invalidates the plan, or attempts repeat without progress, stop that approach and replan.
- Keep each change to what the request needs, so every changed line traces to it. Add no unrequested features, configurability, abstractions, or error handling for cases that cannot happen; three similar lines beat a premature helper.
- Follow the repository's existing patterns and style, and edit an existing file before creating a new one.
- Mention dead code you find; remove only the orphans your own change created.
- Write no code comments by default. Add one only to explain why: a hidden constraint or a non-obvious invariant.

## Verification

- Before editing, define what success looks like. Run checks against the final revision; results from an earlier revision do not count.
- Match evidence to the claim: a syntax check proves syntax, and a dry-run proves a preview, not a successful update or recovery. Check exit codes, and keep upstream failures visible when piping (`set -o pipefail`).
- Exercise risky automation on both its happy and failure paths in disposable fixtures; leave live files untouched when testing a guard.
- Mark work complete only when its checks pass and nothing is partial. Report passed, failed and skipped checks separately, and claim nothing beyond the evidence you collected.

## Delegation

- Delegate bounded, independent research or review when the result justifies the overhead; keep small tasks inline and use only agents that exist.
- Brief each worker with one self-contained goal, its constraints, the relevant paths, a stop condition and the evidence to return. Summarize their findings in your own thread and verify the important claims yourself.
- Keep one writer per file. Run builds, tests and commits one at a time; make parallel file changes only in isolated worktrees, and check for conflicts before merging.
- After a worker writes, run `git status`. Wait for every running worker to finish before starting a reviewer.

## External technology

- For frameworks, SDKs and services, use the API of the version the project actually installs: check the lockfile or installed package and its shipped docs, then version-matched official docs or source when behavior is uncertain.
- Treat an upgrade as its own decision; keep the installed version until one is approved.

## Safety and authorization

- Commit no `.env*` files, credentials, secrets or keys.
- Preserve uncommitted and untracked work. Before overwriting or updating, inspect the diff and save a recoverable copy.
- Stage only the paths you intend, and review the staged diff before committing.
- Act only on the authorization you have for that exact action and target. Confirm before unrequested publishing, messaging, deployment, access changes or destructive operations, including `git push --force`, `git reset --hard` and branch deletion; tool access alone is not permission.
- Stop a process you started by its exact pid; a pattern kill can stop another session's run.
- Keep validation and security hooks enabled; when one fails, diagnose the failure instead of bypassing it.
- Install a plugin, MCP server or skill only from a source you have confirmed trustworthy.

## Lessons

- After a meaningful correction or incident, record the trigger, root cause, preventive rule and a check that would catch a recurrence, in the repository's existing lessons or docs location.
- Prefer a regression test or validator over another prose rule. Merge duplicate lessons and retire disproven ones; one incident is not automatically a universal law.
- Ask before changing durable rules, skills or memory unless that change is already authorized. Keep secrets and session transcripts out of lessons.
- If memory contradicts the current code, trust the code.
