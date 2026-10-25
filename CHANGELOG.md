# Changelog

Mifal 0.3.0 carries the 0.2.4 notes, because 0.2.4 was never tagged or published, plus the work done since. The public release before this one is 0.2.3. macOS only; alpha.

## 0.3.0 (unreleased)

**One release for five agents: OpenCode now gets the Guide, an update stops before moving a skill of yours, doctor names the file each agent reads, and the docs say what was and was not checked.**

Install, update and doctor
- OpenCode gets its own rules file. Mifal writes `~/.config/opencode/AGENTS.md` with its Marked block when that file is missing; OpenCode reads it before the `~/.claude/CLAUDE.md` fallback. If the fallback holds anything besides Mifal's block, the preview names it as the file OpenCode stops reading. A first install prints that as a note; an install over an existing Mifal install stops on it once and needs `./install.sh --overwrite-edits`, because `mifal update` does not re-plan an agent the install recorded as skipped. Mifal still never edits `opencode.json` or any agent settings.
- `mifal update` no longer silently moves a skill of yours. If a release reserves a skill name that a skill of yours already uses, the update lists each clash and changes nothing until you run it again with `--overwrite-edits`, which saves your copy to `~/.agents/mifal/backup/` first. `mifal doctor` shows a note with the count of saved copies and how to restore them. `mifal uninstall` restores a saved copy when its place is free.
- `mifal doctor` no longer reports that agents "read the pool natively". For each agent Mifal serves it names the rules file that holds Mifal's block, and it lists agents it detected but did not serve and a second Claude home that sees the skills without the Guide. It still runs no agent and reads no settings file.

**Update protection starts with 0.3.0.** An update from 0.2.3, or from a local 0.2.4 build, runs the old release's installed code for its first run, and that code cannot stop on a clash: it moves a skill of yours that has a newly reserved name into `~/.agents/mifal/backup/` and carries on. Check `~/.agents/skills/` for skills of yours before updating from 0.2.3. As in 0.2.4, an update from 0.2.3 takes two runs of `mifal update`: the first installs the new release but not the `NOTICE` and `third_party/` licence files and reports success; the second lists the missing files and adds them once you confirm, and `mifal doctor` warns until then.

The method and the validator
- Brief pin. `validate_contracts.py brief-digest` hashes the lead-owned text of a brief above its `## Return` line, ignoring checkbox state. The lead stamps the digest when it dispatches, and `receipt --matt --brief-digest sha256:DIGEST` refuses a receipt whose brief was cut or edited. Without the flag, behaviour is unchanged.
- The research checklist in team-lead's brief guidance uses the research steps the validator requires, so a brief stays valid as phases are ticked.
- Doorbell rule: the return file is authoritative, and a lead checks its expected return files whenever it wakes or between its own steps. A worker's bounded retry runs in the foreground, and a worker that finds the lead's composer holding a draft or unreadable does not send.
- The Guide and skill text are agent-neutral: the launcher clause and the second-owner wording are gone, and the Guide says what the live check found. Three Guide lines: load a skill named by "call the Skill tool" natively or by reading `~/.agents/skills/NAME/SKILL.md`; skip a skill whose tool, CLI or harness you lack and say so; with no sub-agents, run a sub-agent step in a new session or Herdr pane when you have one, and label the result.
- The lead loop's attention check handles every Herdr status: `blocked`, `unknown` and any unrecognised status need attention, with a test for each. The loop is experimental and tested with fake agents.
- Two timing flakes in the event-loop tests are fixed.

Docs
- The README support matrix has a row per agent version and model and a level per cell: L1 Guide and skills, L2 method working alone, L3 team worker, L4 team lead (one lead, one worker, one small task). It was recorded on one Mac on 2026-10-25 on the 0.2.4 code, so it predates the changes above. L2 is stated as a limitation, the lead loop as experimental, and agent-level skill filters (Pi `skills`, Droid `disabledSkills`, Codex `[[skills.config]]`, OpenCode `permission.skill`, and a `.gitignore` inside a skills folder for Pi) as something doctor cannot see.
- INSTALL has one install, update, rollback and uninstall path, and per-agent skill precedence. Rollback has no command: uninstall, then install from a clone of the older tag. After a rollback to 0.2.3, OpenCode reads the `~/.claude/CLAUDE.md` fallback again.
- New ADR 0004, "Mifal never writes through a linked rules file", and the glossary entries "Personal layer" and "Brief pin".
- `maint/rehearse-upgrade.sh` rehearses install, update, uninstall and rollback for all five agents in a disposable home.

Known limits
- No agent passed L2 (the entry gate) as written; an agent working alone keeps its checklist in chat, so the validator's entry check has no record file to run on.
- The ignored-file update guard from 0.2.4 is still planned: if a release adds a tracked file where your clone has a file Git ignores, `mifal update` replaces it, as Git does.
- Each agent has one recorded run as a team worker and one as a team lead (Claude Code with Opus has no lead run), each on one small task; none was rerun on this release's code.

## 0.2.4 (never tagged; included in 0.3.0)

**A safety release: Mifal refuses to act on another home's install or to install an older version over a newer one, carries its licences, and its docs say only what the code does.**

Install, update and doctor
- Every `mifal` command that reads the install's Manifest checks that the Manifest belongs to this home. If `~/.agents/mifal` (or `~/.agents`) is a link to another home's install, `install`, `update`, `uninstall` and `doctor` stop with "belongs to the Mifal install for …, not this home" and change nothing; the message names the link. If your home folder was renamed or moved, Mifal no longer acts on the old install's recorded paths; it says so.
- `./install.sh` from a clone older than the installed version refuses before it writes anything, including while an interrupted install is pending, and names both versions. A clone of 0.2.3 or earlier runs its own installer, which installs its older version; use `mifal update` instead.
- An unreadable or non-UTF-8 `VERSION` in a clone is refused with a message instead of a traceback.
- `mifal doctor`'s completeness check turns off Git's lazy fetching. If the installed revision's file list cannot be read from local objects, as in a partial clone, it warns instead of downloading the missing objects.
- The install copies `NOTICE` and `third_party/` (licences and provenance of the skills Mifal ships) into `~/.agents/mifal/`. `mifal uninstall` removes unchanged copies and keeps edited or diverted paths and anything you added.
- If the installed revision has engine files missing from the Manifest, as after the first update from 0.2.3, `mifal update` lists them and installs them once you confirm, and `mifal doctor` warns about them until then.

The method
- The Guide asks an agent working alone to show its route, phase and next gate and the phase checklist before its first edit, and to ask "Full workflow or cut? Recommended: full workflow." in plain text, then wait. Each phase ends with its own evidence: a failing test before the fix, a passing one after, review findings against a snapshot, and a retro.
- On the debug route, when the `tdd` read and the fix-start Check both carry a time, the validator refuses a record whose `tdd` read comes after the fix started. Missing times are reported as unverified, not refused. These records do not prove the skill was used.

Docs
- Public copy that promised more than the code does is corrected in the README, docs and website. The validator checks a record's fields and selected hashes; it does not verify that tests ran or that skills were used.

Known limits
- If a release adds a tracked file where your clone has a file Git ignores, `mifal update` replaces that file, as Git does. A guard is planned for a later release.
